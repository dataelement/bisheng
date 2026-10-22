import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

import anyio
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError

from bisheng.common.errcode import BaseErrorCode
from bisheng.core.logger import trace_id_var
from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.mcp_server.domain.schemas.identity import McpExecutionIdentity, McpIdentityRequest
from bisheng.mcp_server.domain.services.auth_service import McpAuthService
from bisheng.mcp_server.domain.services.user_context_service import IDENTITY_DENIED_MESSAGE, IDENTITY_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)
WRITE_TOOLS = frozenset({"create_document", "upload_file"})
_execution_audited: ContextVar[bool | None] = ContextVar("mcp_execution_audited", default=None)


def audit_execution(
    name: str, principal: DeveloperTokenPrincipal, identity: McpExecutionIdentity | None, outcome: str, started: float
) -> None:
    if _execution_audited.get() is not None:
        _execution_audited.set(True)
    logger.info(
        "mcp tool=%s token_id=%s token_user_id=%s token_tenant_id=%s user_id=%s tenant_id=%s "
        "trace_id=%s outcome=%s elapsed=%.3f",
        name,
        principal.token_id,
        principal.user.user_id,
        principal.tenant_id,
        identity.user.user_id if identity else None,
        identity.tenant_id if identity else None,
        trace_id_var.get(),
        outcome,
        time.monotonic() - started,
    )


class McpToolRuntime:
    def __init__(
        self, factory: Callable[..., Any], identity_resolver: Callable[..., Awaitable[McpExecutionIdentity]]
    ) -> None:
        self.factory = factory
        self.identity_resolver = identity_resolver

    async def invoke(self, ctx: Context, name: str, params: McpIdentityRequest) -> Any:
        request = ctx.request_context.request
        principal = request.scope.get("state", {}).get("mcp_principal") if request is not None else None
        if principal is None:
            raise ToolError("MCP authentication required")
        started = time.monotonic()
        outcome = "failed"
        identity = None
        try:
            with anyio.fail_after(120 if name in WRITE_TOOLS else 30):
                with anyio.fail_after(IDENTITY_TIMEOUT_SECONDS):
                    identity = await self.identity_resolver(principal, params.external_id)
                with McpAuthService.use_identity(identity):
                    async with self.factory(request, identity.user) as services:
                        operation = getattr(services, name)
                        result = await operation(**params.model_dump(exclude={"external_id"}))
                    outcome = "success"
                    return result
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise ToolError("MCP operation timed out; verify write state before retrying") from exc
        except BaseErrorCode as exc:
            if exc.kwargs.get("mcp_identity_denied"):
                raise ToolError(IDENTITY_DENIED_MESSAGE) from exc
            if name in WRITE_TOOLS and exc.kwargs.get("mcp_write_uncertain"):
                file_id = exc.kwargs.get("file_id")
                safe_id = f" file_id={file_id}" if isinstance(file_id, int) and file_id > 0 else ""
                raise ToolError("Write outcome uncertain; check file state before retrying." + safe_id) from exc
            raise ToolError("Resource denied or unavailable") from exc
        except ValueError as exc:
            raise ToolError("Invalid MCP input or pagination cursor") from exc
        except Exception as exc:
            logger.error("mcp operation failed tool=%s exception_type=%s", name, type(exc).__name__)
            raise ToolError("MCP operation failed") from exc
        finally:
            audit_execution(name, principal, identity, outcome, started)
