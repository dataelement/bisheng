"""Owned local TCP test server; isolated app state, no production middleware connections."""

import socket
import threading
from contextlib import contextmanager

import uvicorn


@contextmanager
def local_http_server(app):
    ready = threading.Event()

    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            ready.set()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = Server(uvicorn.Config(app, log_level="error", access_log=False, lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    try:
        thread.start()
        assert ready.wait(10), "Local HTTP provider did not start"
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        if thread.ident is not None:
            thread.join(10)
        sock.close()
        assert not thread.is_alive(), "Local HTTP server failed to terminate"
