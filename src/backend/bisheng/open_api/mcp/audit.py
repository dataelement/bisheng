"""One audit row per tool call — attributable to the key and its service account.

The generic ``/api/v2`` middleware is short-circuited for this path (it would
only ever record ``POST /api/v2/mcp``, which says nothing about what was done),
so this module is the *only* writer for the MCP face and there is no double row.

What never enters a row: the query text, any retrieved chunk, the full argument
object, and any key material. A retrieval query and its results are knowledge-base
content — copying them into the audit table would turn an access log into a
second copy of the corpus. Only an id summary goes in.
"""

from __future__ import annotations

from typing import Any

from bisheng.core.logger import trace_id_var
from bisheng.database.models.audit_log import AuditLog
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.services.call_audit_service import open_api_call_audit_service

#: Lockstep with ``_UI_VISIBLE_V2_ACTIONS`` (backend) and ``V2_ACTIONS``
#: (platform ``controllers/API/log.ts``); the i18n key is derived, never typed.
MCP_TOOL_CALL_ACTION = "open_api.mcp.tool_call"
MCP_TARGET_TYPE = "mcp_tool"

#: The only keys a ``target`` summary may carry. An allowlist rather than a
#: denylist: a handler that starts passing something new gets it dropped here
#: instead of leaking it into the audit table unnoticed.
TARGET_KEYS = frozenset({"knowledge_ids", "app_id", "table", "dept_id", "user_id"})


def audit_tool_call(
    principal: OpenApiPrincipal | None,
    *,
    tool: str,
    category: str | None = None,
    target: dict[str, Any] | None = None,
    outcome: str,
    latency_ms: int,
    ip_address: str | None = None,
) -> None:
    """Record one ``tools/call``. ``outcome`` is ``success`` / ``denied:<code>`` / ``error:<code>``."""

    _enqueue(
        principal,
        target_id=tool,
        metadata={
            "tool": tool,
            "category": category,
            "target": _safe_target(target),
            "outcome": outcome,
            "latency_ms": int(latency_ms),
        },
        ip_address=ip_address,
    )


def audit_transport_refusal(
    principal: OpenApiPrincipal | None,
    *,
    code: int,
    latency_ms: int = 0,
    ip_address: str | None = None,
) -> None:
    """Record a refusal that never reached a tool (bad key, ``delegate``, identity header).

    Same action as a tool call, with ``target_id="-"``: "this key was refused at
    the door" and "this key called a tool" belong on one timeline, and a
    separate action would mean two filters to remember on the audit page.
    """

    _enqueue(
        principal,
        target_id="-",
        metadata={
            "tool": None,
            "category": None,
            "target": {},
            "outcome": f"denied:{int(code)}",
            "latency_ms": int(latency_ms),
        },
        ip_address=ip_address,
    )


def _safe_target(target: dict[str, Any] | None) -> dict[str, Any]:
    return {key: value for key, value in (target or {}).items() if key in TARGET_KEYS}


def _enqueue(
    principal: OpenApiPrincipal | None,
    *,
    target_id: str,
    metadata: dict[str, Any],
    ip_address: str | None,
) -> None:
    tenant_id = principal.tenant_id if principal else None
    metadata = {
        "credential_id": principal.credential_id if principal else None,
        "actor_kind": principal.actor_kind if principal else None,
        "actor_id": principal.actor_id if principal else None,
        "resource_owner_user_id": principal.resource_owner_user_id if principal else None,
        **metadata,
        "trace_id": str(trace_id_var.get() or ""),
    }
    # Same operator spelling as the v2 middleware: a natural person is the
    # operator, a service account is named instead so the row reads as "this
    # key did it" rather than as an action by whoever owns it.
    operator_id = principal.actor_id if principal is not None and principal.actor_kind == "natural_person" else 0
    operator_name = (
        principal.actor_name if principal is not None and principal.actor_kind == "service_account" else None
    )
    open_api_call_audit_service.enqueue(
        AuditLog(
            tenant_id=tenant_id,
            operator_id=operator_id,
            operator_name=operator_name,
            operator_tenant_id=tenant_id,
            action=MCP_TOOL_CALL_ACTION,
            target_type=MCP_TARGET_TYPE,
            target_id=target_id,
            ip_address=ip_address,
            audit_metadata=metadata,
        )
    )


__all__ = [
    "MCP_TARGET_TYPE",
    "MCP_TOOL_CALL_ACTION",
    "TARGET_KEYS",
    "audit_tool_call",
    "audit_transport_refusal",
]
