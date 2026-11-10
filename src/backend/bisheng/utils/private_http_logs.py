"""Suppress HTTP library payload metadata only in the current private request."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar

_private_http = ContextVar("private_tool_http", default=False)


class _PrivateHttpFilter(logging.Filter):
    def filter(self, record):
        return not _private_http.get()


# Logger filters run before handlers, including the application log bridge.
# Other tasks retain their existing logging behavior.
for _name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"):
    logging.getLogger(_name).addFilter(_PrivateHttpFilter())


@contextmanager
def private_http_logs():
    token = _private_http.set(True)
    try:
        yield
    finally:
        _private_http.reset(token)
