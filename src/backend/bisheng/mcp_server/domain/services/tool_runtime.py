import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import anyio
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel

from bisheng.common.errcode import BaseErrorCode
from bisheng.core.logger import trace_id_var
from bisheng.mcp_server.domain.services.auth_service import McpAuthService

logger = logging.getLogger(__name__)
WRITE_TOOLS = frozenset({"create_document", "upload_file"})


class McpToolRuntime:
    def __init__(self, factory: Callable[..., Any]) -> None:
        self.factory = factory

    async def invoke(self, ctx: Context, name: str, params: BaseModel) -> Any:
        request = ctx.request_context.request
        principal = request.scope.get("state", {}).get("mcp_principal") if request is not None else None
        if principal is None:
            raise ToolError("MCP authentication required")
        started = time.monotonic()
        outcome = "failed"
        try:
            with McpAuthService.use_identity(principal):
                async with self.factory(request, principal.user) as services:
                    operation = getattr(services, name)
                    with anyio.fail_after(120 if name in WRITE_TOOLS else 30):
                        result = await operation(**params.model_dump())
                    outcome = "success"
                    return result
        except asyncio.TimeoutError as exc:
            raise ToolError("MCP operation timed out; verify write state before retrying") from exc
        except BaseErrorCode as exc:
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
            logger.info(
                "mcp tool=%s token_id=%s user_id=%s tenant_id=%s trace_id=%s outcome=%s elapsed=%.3f",
                name,
                principal.token_id,
                principal.user.user_id,
                principal.tenant_id,
                trace_id_var.get(),
                outcome,
                time.monotonic() - started,
            )
