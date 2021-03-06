"""
This module provides facilities for experiment to execute code remotely on
RPC servers.

The remotely executed code has direct access to the resources on the remote end,
so it can transfer vlarge amounts of data with them, and only exchange higher-level,
processed data with the client (and over the network).

RPC servers with support for remote execution contain an additional target
that gives RPC access to instances of :class:`.RemoteExecServer`. One such instance
is created per client connection and manages one Python namespace in which the
client can execute arbitrary code by calling the methods of
:class:`.RemoteExecServer`.

The namespaces are initialized with the following global values:

  * ``controller_driver`` - the target object of the RPC server.
  * ``controller_initial_namespace`` - a server-wide dictionary copied
    when initializing a new namespace.
  * all values from ``controller_initial_namespace``.

With ARTIQ, access to a controller with support for remote execution is done
through an additional device database entry of this form: ::

    "$REXEC_DEVICE_NAME": {
        "type": "controller_aux_target",
        "controller": "$CONTROLLER_DEVICE_NAME",
        "target_name": "$TARGET_NAME_FOR_REXEC"
    }

Specifying ``target_name`` is mandatory in all device database entries for all
controllers with remote execution support.

"""

from functools import partial
import inspect

from sipyco.pc_rpc import simple_server_loop


__all__ = ["RemoteExecServer", "simple_rexec_server_loop", "connect_global_rpc"]


class RemoteExecServer:
    """RPC target created at each connection by controllers with remote
    execution support. Manages one Python namespace and provides RPCs
    for code execution.
    """
    def __init__(self, initial_namespace):
        self.namespace = dict(initial_namespace)
        # The module actually has to exist, otherwise it breaks e.g. Numba
        self.namespace["__name__"] = "sipyco.remote_exec"

    def add_code(self, code):
        """Executes the specified code in the namespace.

        :param code: a string containing valid Python code
        """
        exec(code, self.namespace)

    def call(self, function, *args, **kwargs):
        """Calls a function in the namespace, passing it positional and
        keyword arguments, and returns its value.

        :param function: a string containing the name of the function to
            execute.
        """
        return self.namespace[function](*args, **kwargs)


def simple_rexec_server_loop(target_name, target, host, port,
                             description=None):
    """Runs a server with remote execution support, until an exception is
    raised (e.g. the user hits Ctrl-C) or termination is requested by a client.
    """
    initial_namespace = {"controller_driver": target}
    initial_namespace["controller_initial_namespace"] = initial_namespace
    targets = {
        target_name: target,
        target_name + "_rexec": lambda: RemoteExecServer(initial_namespace)
    }
    simple_server_loop(targets, host, port, description)


def connect_global_rpc(controller_rexec, host=None, port=3251,
                       target="master_dataset_db", name="dataset_db"):
    """Creates a global RPC client in a RPC server that is used across
    all remote execution connections.

    The default parameters are designed to connects to an ARTIQ dataset
    database (i.e. gives direct dataset access to experiment code
    remotely executing in controllers).

    If a global object with the same name already exists, the function does
    nothing.

    :param controller_rexec: the RPC client connected to the server's
        remote execution interface.
    :param host: the host name to connect the RPC client to. Default is the
        local end of the remote execution interface (typically, the ARTIQ
        master).
    :param port: TCP port to connect the RPC client to.
    :param target: name of the RPC target.
    :param name: name of the object to insert into the global namespace.
    """
    if host is None:
        host = controller_rexec.get_local_host()
    code = """
if "{name}" not in controller_initial_namespace:
    import atexit
    from sipyco.pc_rpc import Client

    {name} = Client("{host}", {port}, "{target}")
    atexit.register({name}.close_rpc)
    controller_initial_namespace["{name}"] = {name}
""".format(host=host, port=port, target=target, name=name)
    controller_rexec.add_code(code)
