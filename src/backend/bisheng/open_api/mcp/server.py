"""The MCP server itself: tool listing, tool dispatch, and the route factory.

Transport decisions worth knowing before changing anything here (design D1):

* **stateless + JSON.** Every ``tools/call`` is one self-contained HTTP POST, so
  "revoked / expired / re-scoped takes effect on the next call" is structural —
  there is no established session to hunt down and tear down, and nothing about
  the credential is cached between calls. It also means nginx and the commercial
  gateway pass it through with no configuration at all.
* **An exact ``Route``, not ``app.mount``.** Starlette compiles a ``Mount``'s
  path as ``^/api/v2/mcp/(?P<path>.*)$``, so the bare ``/api/v2/mcp`` misses and
  ``redirect_slashes`` answers 307. The official Python client follows redirects
  and would hide it; other clients and the Java gateway do not promise to follow
  a 307 on POST. ``Route`` has no such rule.
* **DNS-rebinding protection off.** ``FastMCP`` turns it on automatically for a
  ``127.0.0.1`` host and then only allows ``localhost``-shaped ``Host`` headers,
  while nginx forwards the real one (``proxy_set_header Host $host``) — every
  request from a real deployment would be a 421. The trust boundary here is the
  reverse proxy plus the credential, not the ``Host`` header.

Assembly order is load-bearing (pit 2): ``streamable_http_app()`` must be called
once to build the session manager lazily — reading ``server.session_manager``
before that raises — and its returned Starlette app is thrown away, because the
route we want is our own gate wrapping the ASGI handler.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from loguru import logger
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool as MCPTool
from pydantic import ValidationError
from starlette.routing import Route

from bisheng.common.errcode.mcp_face import McpToolArgumentInvalidError
from bisheng.open_api.domain.context import get_current_open_api_principal
from bisheng.open_api.mcp import registry
from bisheng.open_api.mcp.audit import audit_tool_call
from bisheng.open_api.mcp.errors import McpToolError, to_tool_error
from bisheng.open_api.mcp.gate import McpAccessGate

#: The one URL. No sub-paths, no trailing slash — see the module docstring.
MCP_ROUTE_PATH = "/api/v2/mcp"

SERVER_NAME = "bisheng"
SERVER_INSTRUCTIONS = (
    "BiSheng platform tools. Every tool runs as the credential itself: what you can see is "
    "what an administrator granted this service account, never more. Call tools/list first — "
    "it shows only the tools this credential's scopes cover. Refusals are JSON with "
    "code / category / reason / next_step; read next_step before retrying."
)


class BishengMcpServer(FastMCP):
    """``FastMCP`` with a per-credential tool list and an authorising dispatcher."""

    def __init__(self) -> None:
        super().__init__(
            name=SERVER_NAME,
            instructions=SERVER_INSTRUCTIONS,
            stateless_http=True,
            json_response=True,
            streamable_http_path="/",
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        for spec in registry.TOOL_REGISTRY:
            self.add_tool(spec.handler, name=spec.name, description=spec.description)

    async def list_tools(self) -> list[MCPTool]:
        """Only what this credential's scopes cover (AC-04).

        A credential with no scopes still completes the handshake and gets an
        empty list: connecting is not a capability, and refusing the handshake
        would make "no scopes yet" look like "your key is broken".
        """

        principal = get_current_open_api_principal()
        visible = {spec.name for spec in registry.visible_tools(principal)}
        return [
            MCPTool(
                name=info.name,
                title=info.title,
                description=info.description,
                inputSchema=info.parameters,
                outputSchema=info.output_schema,
                annotations=info.annotations,
                icons=info.icons,
                _meta=info.meta,
            )
            for info in self._tool_manager.list_tools()
            if info.name in visible
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Authorise, dispatch, audit — and make sure a refusal stays parseable."""

        principal = get_current_open_api_principal()
        started = perf_counter()
        spec = None
        try:
            spec = registry.require_tool(principal, name)
            result = await super().call_tool(name, arguments)
        except ToolError as exc:
            # Pit 19: ``Tool.run`` re-wraps whatever the handler raised as
            # ``ToolError(f"Error executing tool {name}: {e}")``. Handing that
            # straight back prefixes our JSON with English prose and the client's
            # ``json.loads`` fails — so unwrap the original off ``__cause__``.
            cause = exc.__cause__
            if isinstance(cause, ValidationError):
                cause = McpToolArgumentInvalidError(errors=_validation_summary(cause))
            error = to_tool_error(cause if cause is not None else exc)
            self._audit(principal, name, spec, arguments, error, started)
            raise error from exc
        except ValidationError as exc:
            error = to_tool_error(McpToolArgumentInvalidError(errors=_validation_summary(exc)))
            self._audit(principal, name, spec, arguments, error, started)
            raise error from exc
        except Exception as exc:
            error = to_tool_error(exc)
            if error.category == "internal":
                # The payload deliberately carries no exception text; the
                # traceback has to live somewhere, so it lives in our log.
                logger.exception(f"open_api.mcp tool={name} failed")
            self._audit(principal, name, spec, arguments, error, started)
            raise error from exc

        latency_ms = _elapsed_ms(started)
        audit_tool_call(
            principal,
            tool=name,
            category=spec.category if spec else None,
            target=_target_summary(arguments),
            outcome="success",
            latency_ms=latency_ms,
        )
        logger.info(
            "open_api.mcp | tool={} credential_id={} outcome=success latency_ms={}",
            name,
            getattr(principal, "credential_id", None),
            latency_ms,
        )
        return result

    @staticmethod
    def _audit(principal, name: str, spec, arguments: dict[str, Any], error: McpToolError, started: float) -> None:
        latency_ms = _elapsed_ms(started)
        outcome = f"{'denied' if error.category != 'internal' else 'error'}:{error.code}"
        audit_tool_call(
            principal,
            tool=name,
            category=spec.category if spec else None,
            target=_target_summary(arguments),
            outcome=outcome,
            latency_ms=latency_ms,
        )
        logger.info(
            "open_api.mcp | tool={} credential_id={} outcome={} latency_ms={}",
            name,
            getattr(principal, "credential_id", None),
            outcome,
            latency_ms,
        )


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _validation_summary(exc: ValidationError) -> list[dict[str, Any]]:
    """Field paths and messages only — never the submitted values."""

    summary = []
    for error in exc.errors():
        summary.append(
            {
                "loc": [str(part) for part in error.get("loc", ())],
                "type": error.get("type"),
                "msg": error.get("msg"),
            }
        )
    return summary


def _target_summary(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Which objects a call was about — ids only, never the query or the values."""

    arguments = arguments or {}
    summary: dict[str, Any] = {}
    for key in ("app_id", "table", "dept_id", "user_id"):
        if arguments.get(key) is not None:
            summary[key] = arguments[key]
    if arguments.get("knowledge_ids"):
        summary["knowledge_ids"] = list(arguments["knowledge_ids"])
    return summary


def new_mcp_server() -> BishengMcpServer:
    """A server whose session manager exists and has never been run.

    ``session_manager`` is built lazily by ``streamable_http_app()`` and raises
    if read before — and ``run()`` may be entered only once per instance, so a
    second app in the same process (a test) needs its own server, not a second
    pass over the shared one.
    """

    server = BishengMcpServer()
    # Called for the side effect; the Starlette app it returns is not what we
    # serve — our own gate wraps the ASGI handler instead (pit 2).
    server.streamable_http_app()
    return server


_server: BishengMcpServer | None = None


def get_mcp_server() -> BishengMcpServer:
    """The process's single server instance (one per uvicorn worker, correctly)."""

    global _server
    if _server is None:
        _server = new_mcp_server()
    return _server


def build_mcp_route(server: BishengMcpServer | None = None) -> Route:
    """The single route ``main.py`` appends when the open-capability layer is on."""

    server = server or get_mcp_server()
    return Route(
        MCP_ROUTE_PATH,
        endpoint=McpAccessGate(StreamableHTTPASGIApp(server.session_manager)),
        # GET (an SSE stream) and DELETE (end session) are registered so a client
        # gets the SDK's own standard refusal in stateless mode rather than
        # Starlette's bare 405.
        methods=["GET", "POST", "DELETE"],
    )


def mcp_session_manager_run(server: BishengMcpServer | None = None):
    """Lifespan context for the session manager — entered once per instance."""

    return (server or get_mcp_server()).session_manager.run()


__all__ = [
    "MCP_ROUTE_PATH",
    "BishengMcpServer",
    "build_mcp_route",
    "get_mcp_server",
    "mcp_session_manager_run",
    "new_mcp_server",
]
