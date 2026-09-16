"""The single hole in the wall — hosted applications' only route out (D12-C L2).

An application container sits on an ``--internal`` network and is handed
``HTTP_PROXY`` / ``HTTPS_PROXY`` pointing here. This process is the one place in
the deployment that can see a *hostname* on an outbound connection, which is the
only thing AC-16's "只放行平台 API 与应用包声明的域名" can be decided against — a
firewall sees an address, and one address serves a hundred names.

It is deliberately the dumbest proxy that can enforce that:

* **``CONNECT`` is a blind tunnel.** The host is taken from the request line and
  checked before a single byte is forwarded; after that the two sockets are
  pumped without inspection. No TLS interception, no certificate authority, no
  ability to read anybody's traffic — the platform decides *whether* a
  connection may exist, never what travels over it.
* **Absolute-form HTTP** (``GET http://host/path``) is the plaintext twin and
  goes through the same check, then is rewritten to origin form. Each such
  connection carries one request (``Connection: close``): keep-alive would mean
  re-checking a host per request on a connection already opened, and the saving
  is nothing next to the confusion.
* **Nothing else is a proxy request.** Origin-form requests, other methods on
  the proxy itself — refused. In particular there is no status or admin
  endpoint: the process is reachable from every hosted application, so its own
  surface is one thing worth keeping at zero.

Identity comes from ``Proxy-Authorization``, which every HTTP client fills in on
its own from the credentials in the injected proxy URL. The policy it is checked
against is the file :class:`runtime_manager.egress.EgressPolicyStore` writes, so
this process depends on the manager's *output*, never on the manager being up:
restarting the orchestrator must not take every application's outbound traffic
with it.

Run it as its own process (``python -m runtime_manager.egress_proxy``) — same
image, same package, same configuration. It shares nothing with the intent API
but the policy file, and it must never be given the docker socket.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from runtime_manager.config import Config, get_config
from runtime_manager.egress import (
    DENY_UNKNOWN_PRINCIPAL,
    EgressPolicyStore,
    authorize,
    get_policy_store,
)

logger = logging.getLogger(__name__)

#: Request line + headers. Generous for a real request, small enough that a
#: client which never sends a blank line cannot hold memory here.
MAX_HEADER_BYTES = 64 * 1024
#: How long a client has to finish its request line and headers.
HEADER_TIMEOUT_SECONDS = 15.0
#: Connect timeout to the upstream. Short: the caller is a hosted application
#: with its own timeout, and a hanging CONNECT is indistinguishable from a hung
#: application to whoever is looking at it.
UPSTREAM_TIMEOUT_SECONDS = 15.0
#: Bytes moved per pump iteration.
CHUNK = 64 * 1024

#: Hop-by-hop headers this proxy consumes and must not pass on.
_HOP_BY_HOP = {"proxy-authorization", "proxy-connection", "connection", "keep-alive", "te", "trailer", "upgrade"}


@dataclass(frozen=True)
class ProxyRequest:
    method: str
    target: str
    version: str
    headers: list[tuple[str, str]]

    def header(self, name: str) -> str:
        name = name.lower()
        return next((value for key, value in self.headers if key.lower() == name), "")


def _response(status: int, phrase: str, *, reason: str = "", detail: str = "", extra: str = "") -> bytes:
    """A proxy answer whose body is the sentence the developer needs.

    The body matters more than usual here: this refusal surfaces inside somebody
    else's application as an HTTP error from a library they did not write, and
    "403 Forbidden" with nothing in it sends them hunting in the wrong system.
    """
    body = f'{{"error":"{reason}","message":"{detail}"}}'.encode()
    head = (
        f"HTTP/1.1 {status} {phrase}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"{extra}"
        f"Connection: close\r\n\r\n"
    ).encode()
    return head + body


def parse_target(method: str, target: str) -> tuple[str, int, str]:
    """``(host, port, path)`` for both proxy request forms.

    ``path`` is empty for ``CONNECT`` and is what the request line is rewritten
    to for the absolute form.
    """
    if method == "CONNECT":
        host, _, port = target.rpartition(":")
        if not host or not port.isdigit():
            return "", 0, ""
        return host.strip("[]").lower(), int(port), ""
    if "://" not in target:
        return "", 0, ""
    from urllib.parse import urlsplit

    split = urlsplit(target)
    if split.scheme not in {"http", "https"} or not split.hostname:
        return "", 0, ""
    port = split.port or (443 if split.scheme == "https" else 80)
    path = split.path or "/"
    if split.query:
        path = f"{path}?{split.query}"
    return split.hostname.lower(), port, path


async def _read_head(reader: asyncio.StreamReader) -> ProxyRequest | None:
    raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=HEADER_TIMEOUT_SECONDS)
    if len(raw) > MAX_HEADER_BYTES:
        return None
    lines = raw.decode("latin-1").split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) != 3:
        return None
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line:
            continue
        key, sep, value = line.partition(":")
        if sep:
            headers.append((key.strip(), value.strip()))
    return ProxyRequest(method=parts[0].upper(), target=parts[1], version=parts[2], headers=headers)


async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(CHUNK)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (OSError, asyncio.IncompleteReadError):
        pass
    finally:
        _close(writer)


def _close(writer: asyncio.StreamWriter) -> None:
    try:
        writer.close()
    except OSError:  # pragma: no cover - already gone
        pass


class EgressProxy:
    """The server. One instance owns one listening socket and one policy store."""

    def __init__(self, config: Config, store: EgressPolicyStore | None = None) -> None:
        self._config = config
        self._store = store if store is not None else get_policy_store(config)
        self._server: asyncio.AbstractServer | None = None

    @property
    def sockets(self):  # pragma: no cover - trivial accessor used by tests
        return self._server.sockets if self._server else ()

    async def start(self, host: str = "", port: int = 0) -> asyncio.AbstractServer:
        if not host and not port:
            host, port = _split_listen(self._config.egress_listen)
        self._server = await asyncio.start_server(self.handle, host, port)
        return self._server

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def serve_forever(self) -> None:  # pragma: no cover - process entry point
        server = self._server or await self.start()
        async with server:
            await server.serve_forever()

    # -- connection handling ----------------------------------------------
    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await self._handle(reader, writer)
        except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, OSError):
            _close(writer)
        except Exception:  # pragma: no cover - a bug here must not kill the listener
            logger.exception("egress proxy connection failed")
            _close(writer)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await _read_head(reader)
        if request is None:
            await self._refuse(
                writer, 400, "Bad Request", "bad_request", "this port speaks only the HTTP proxy protocol"
            )
            return

        host, port, path = parse_target(request.method, request.target)
        if not host:
            await self._refuse(
                writer,
                400,
                "Bad Request",
                "bad_request",
                "not a proxy request — reach the internet through HTTP_PROXY / HTTPS_PROXY, which the platform injects",
            )
            return

        decision, principal = authorize(self._store, request.header("proxy-authorization"), host, port)
        if not decision.allowed:
            logger.warning(
                "rtm.egress_deny principal=%s host=%s port=%s reason=%s", principal or "-", host, port, decision.reason
            )
            if decision.reason == DENY_UNKNOWN_PRINCIPAL:
                await self._refuse(
                    writer,
                    407,
                    "Proxy Authentication Required",
                    decision.reason,
                    decision.detail,
                    extra='Proxy-Authenticate: Basic realm="bisheng-egress"\r\n',
                )
            else:
                await self._refuse(writer, 403, "Forbidden", decision.reason, decision.detail)
            return

        logger.info("rtm.egress_allow principal=%s host=%s port=%s", principal, host, port)
        await self._forward(request, reader, writer, host, port, path)

    async def _refuse(
        self, writer: asyncio.StreamWriter, status: int, phrase: str, reason: str, detail: str, extra: str = ""
    ) -> None:
        writer.write(_response(status, phrase, reason=reason, detail=detail, extra=extra))
        try:
            await writer.drain()
        except OSError:  # pragma: no cover - client already gone
            pass
        _close(writer)

    async def _forward(
        self,
        request: ProxyRequest,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        host: str,
        port: int,
        path: str,
    ) -> None:
        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=UPSTREAM_TIMEOUT_SECONDS
            )
        except (TimeoutError, OSError) as exc:
            # 502, not 403: the destination *is* allowed and simply did not
            # answer. Conflating the two would send a developer to the manifest
            # when the fix is at the other end of the wire.
            await self._refuse(writer, 502, "Bad Gateway", "upstream_unreachable", f"cannot reach {host}:{port}: {exc}")
            return

        if request.method == "CONNECT":
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
        else:
            head = [f"{request.method} {path} {request.version}"]
            head += [f"{key}: {value}" for key, value in request.headers if key.lower() not in _HOP_BY_HOP]
            head.append("Connection: close")
            up_writer.write(("\r\n".join(head) + "\r\n\r\n").encode("latin-1"))
            await up_writer.drain()

        await asyncio.gather(_pump(reader, up_writer), _pump(up_reader, writer))


def _split_listen(listen: str) -> tuple[str, int]:
    host, _, port = listen.rpartition(":")
    return (host or "0.0.0.0"), (int(port) if port.isdigit() else 3128)


async def _serve() -> None:  # pragma: no cover - process entry point
    config = get_config()
    if not config.egress_enabled:
        # Refusing to start is right: the only reason to run this process is to
        # be the address instances were told to dial, and without
        # RTM_EGRESS_PROXY nothing was ever told to dial it.
        raise SystemExit("RTM_EGRESS_PROXY is unset — the egress layer is not deployed, so this process has no callers")
    proxy = EgressProxy(config)
    host, port = _split_listen(config.egress_listen)
    await proxy.start(host, port)
    logger.info("egress proxy listening on %s:%s, policy %s", host, port, config.egress_policy_path)
    await proxy.serve_forever()


def main() -> None:  # pragma: no cover - process entry point
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [egress-proxy] %(name)s: %(message)s",
    )
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":  # pragma: no cover
    main()
