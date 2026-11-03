"""Open WebSocket connections, indexed by ``(app, user)`` — D6 invariant ②.

This registry is the reason app-proxy is home-grown rather than an nginx
location: a reverse proxy in the wild has no notion of "close every socket this
user holds into this app", and that operation is exactly what "revoke access"
and "stop the application" mean for a connection that is already open. The
HTTP path re-asks the verdict on every request; a socket asked once, at the
handshake, and would otherwise stay open for hours after the answer changed.

Two things it is **not**:

* **Not shared across processes.** It is a dict in this worker. The backend's
  stop / delete / revoke path is expected to POST ``/internal/connections/close``
  to every app-proxy it fronts (the backend half of T081 — not wired yet; the
  proxy address list is a backend setting still to be added), and a proxy that
  push did not reach — a second node, a second worker, a restart in between —
  is covered by the per-connection re-authorisation loop in
  :mod:`app_proxy.websocket`, which is the safety net, not the mechanism. Run
  app-proxy with one worker per host, or accept that the push is best-effort
  and the re-check interval is the real bound.
* **Not a permission store.** It knows *who* holds *what* socket; whether they
  still may is always the backend's answer.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Connection:
    """One proxied socket. ``closed`` is resolved by whoever decides to end it."""

    conn_id: int
    app_id: str
    user_id: str | None
    slug: str
    request_id: str
    closed: asyncio.Future = field(repr=False)


class ConnectionRegistry:
    def __init__(self) -> None:
        self._by_id: dict[int, Connection] = {}
        self._ids = itertools.count(1)

    def register(self, *, app_id: str, user_id: str | None, slug: str, request_id: str) -> Connection:
        loop = asyncio.get_running_loop()
        connection = Connection(
            conn_id=next(self._ids),
            app_id=app_id,
            user_id=str(user_id) if user_id is not None else None,
            slug=slug,
            request_id=request_id,
            closed=loop.create_future(),
        )
        self._by_id[connection.conn_id] = connection
        return connection

    def unregister(self, connection: Connection) -> None:
        self._by_id.pop(connection.conn_id, None)

    def close_for(self, app_id: str, *, user_ids: list[str] | None = None, code: int, reason: str = "") -> int:
        """Ask every matching connection to end with ``code``; returns how many.

        ``user_ids=None`` means every connection into the app (stop / delete /
        a department-wide revoke whose members we cannot enumerate here); a
        list narrows it to those users. The socket is not touched from here —
        its own handler observes ``closed`` and performs the close on both
        sides, so the close frames go out on the connection's own task.
        """
        wanted = None if user_ids is None else {str(user_id) for user_id in user_ids}
        closed = 0
        for connection in list(self._by_id.values()):
            if connection.app_id != app_id:
                continue
            if wanted is not None and connection.user_id not in wanted:
                continue
            if not connection.closed.done():
                connection.closed.set_result((code, reason))
            closed += 1
        return closed

    def count(self, app_id: str | None = None) -> int:
        if app_id is None:
            return len(self._by_id)
        return sum(1 for connection in self._by_id.values() if connection.app_id == app_id)

    def clear(self) -> None:
        """Test seam only: forget every entry without closing anything."""
        self._by_id.clear()


#: Process-wide instance; the WS handler registers into it and the internal
#: close endpoint drains it.
registry = ConnectionRegistry()
