"""The declarative tool table: name → scope → handler (design D3).

Both halves of the scope rule live here, and both are necessary. Filtering
``tools/list`` alone leaves the call path open, so the list becomes advice rather
than a boundary; checking only on call makes an agent discover its limits by
hitting walls, which for a caller with no human in it means a loop of failures.

A refusal names the missing scope (``data.required``) instead of saying "unknown
tool": the developer's next move is to ask an administrator to tick one box, and
"unknown tool" does not tell them which.

``available()`` is how a tool whose server-side dependency has not merged yet
stays *absent* rather than broken — F051's name resolver for ③, the retrieval
facade for ①②. Absent is the honest answer, and the scope-matrix test takes its
denominator from the available set so a staged rollout does not turn CI red.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from bisheng.common.errcode.app_publish import AppPublishRuntimeLayerDisabledError
from bisheng.common.errcode.mcp_face import McpToolScopeMissingError, McpUnknownToolError
from bisheng.common.services.config_service import settings
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.mcp.tools import apps, identity, knowledge, models

# Tool categories, as they appear in the PRD's six-row table. Carried on each
# spec so the audit row says which family a call belonged to without parsing the
# tool name.
CATEGORY_KNOWLEDGE_SEARCH = "knowledge_search"
CATEGORY_KNOWLEDGE_LIST = "knowledge_list"
CATEGORY_MODEL_LIST = "model_list"
CATEGORY_IDENTITY = "identity"
CATEGORY_APP_DATA = "app_data"
CATEGORY_APP_STATE = "app_state"


def _always() -> bool:
    return True


@dataclass(frozen=True)
class McpToolSpec:
    name: str
    category: str
    scope: str
    handler: Callable[..., Any]
    description: str
    requires_app_runtime: bool = False
    #: Whether this tool's server-side dependency exists on this tree.
    available: Callable[[], bool] = field(default=_always)


TOOL_REGISTRY: tuple[McpToolSpec, ...] = (
    # ① / ② knowledge — both through the unified retrieval facade.
    McpToolSpec(
        name="bisheng_knowledge_search",
        category=CATEGORY_KNOWLEDGE_SEARCH,
        scope="knowledge:read",
        handler=knowledge.bisheng_knowledge_search,
        description=(
            "Search the knowledge bases this credential was granted and return citable chunks. "
            "Omit knowledge_ids to search every granted base; naming one that is not reachable "
            "refuses the whole request rather than quietly returning less."
        ),
        available=knowledge.facade_available,
    ),
    McpToolSpec(
        name="bisheng_knowledge_list",
        category=CATEGORY_KNOWLEDGE_LIST,
        scope="knowledge:read",
        handler=knowledge.bisheng_knowledge_list,
        description=(
            "List the knowledge bases this credential can search, with their ids and names. "
            "Start here when you need an id for the search tool or for an application's "
            "capability declaration."
        ),
        available=knowledge.facade_available,
    ),
    # ③ models — names resolved by the model protocol face, never re-derived.
    McpToolSpec(
        name="bisheng_model_list",
        category=CATEGORY_MODEL_LIST,
        scope="model:invoke",
        handler=models.bisheng_model_list,
        description=(
            "List this tenant's enabled models with the exact name to call each one by on the "
            "OpenAI-compatible endpoint, plus whether it is a chat model."
        ),
        available=models.resolver_available,
    ),
    # ④ identity and organisation — tenant-wide, never narrowed.
    McpToolSpec(
        name="bisheng_identity_get_user",
        category=CATEGORY_IDENTITY,
        scope="identity:read",
        handler=identity.bisheng_identity_get_user,
        description="Look up one person's name, status, departments and roles by user id.",
    ),
    McpToolSpec(
        name="bisheng_org_tree",
        category=CATEGORY_IDENTITY,
        scope="identity:read",
        handler=identity.bisheng_org_tree,
        description="Return this tenant's whole department tree.",
    ),
    McpToolSpec(
        name="bisheng_dept_members",
        category=CATEGORY_IDENTITY,
        scope="identity:read",
        handler=identity.bisheng_dept_members,
        description="List one department's members, one page at a time.",
    ),
    # ⑤ application data — owner-only, read and row-level write, no DDL.
    McpToolSpec(
        name="bisheng_app_db_tables",
        category=CATEGORY_APP_DATA,
        scope="app:manage",
        handler=apps.bisheng_app_db_tables,
        description="List the tables in one of your applications' own database.",
        requires_app_runtime=True,
    ),
    McpToolSpec(
        name="bisheng_app_db_schema",
        category=CATEGORY_APP_DATA,
        scope="app:manage",
        handler=apps.bisheng_app_db_schema,
        description=(
            "Read one table's columns and key. The schema is declared in bisheng-app.yaml and "
            "changed through the publish pipeline — there is no DDL on this face."
        ),
        requires_app_runtime=True,
    ),
    McpToolSpec(
        name="bisheng_app_db_rows",
        category=CATEGORY_APP_DATA,
        scope="app:manage",
        handler=apps.bisheng_app_db_rows,
        description="Read one page of rows from one of your applications' tables.",
        requires_app_runtime=True,
    ),
    McpToolSpec(
        name="bisheng_app_db_row_update",
        category=CATEGORY_APP_DATA,
        scope="app:manage",
        handler=apps.bisheng_app_db_row_update,
        description="Update one row by its key. Every write is audited with its before and after.",
        requires_app_runtime=True,
    ),
    # ⑥ application state and logs — owner-only reads.
    McpToolSpec(
        name="bisheng_app_status",
        category=CATEGORY_APP_STATE,
        scope="app:manage",
        handler=apps.bisheng_app_status,
        description=(
            "Runtime state of one of your applications plus its latest release's approval "
            "outcome, including the full rejection reason."
        ),
        requires_app_runtime=True,
    ),
    McpToolSpec(
        name="bisheng_app_logs",
        category=CATEGORY_APP_STATE,
        scope="app:manage",
        handler=apps.bisheng_app_logs,
        description=(
            "Recent output of one of your applications — the same lines its detail page and the "
            "CLI show. Platform-side logs are not part of it."
        ),
        requires_app_runtime=True,
    ),
)

TOOLS_BY_NAME: dict[str, McpToolSpec] = {spec.name: spec for spec in TOOL_REGISTRY}


def app_runtime_enabled() -> bool:
    return bool(settings.app_runtime.enabled)


def installed_tools() -> list[McpToolSpec]:
    """Every tool whose server-side dependency exists on this tree."""

    return [spec for spec in TOOL_REGISTRY if spec.available()]


def visible_tools(principal: OpenApiPrincipal | None) -> list[McpToolSpec]:
    """What this credential may see — the same predicate ``require_tool`` enforces."""

    if principal is None:
        return []
    runtime_on = app_runtime_enabled()
    return [
        spec
        for spec in installed_tools()
        if principal.has_scope(spec.scope) and (runtime_on or not spec.requires_app_runtime)
    ]


def require_tool(principal: OpenApiPrincipal | None, name: str) -> McpToolSpec:
    """Admit one call, or raise the refusal that tells the agent what to do next."""

    spec = TOOLS_BY_NAME.get(name)
    if spec is None or not spec.available():
        raise McpUnknownToolError(tool=name)
    if principal is None or not principal.has_scope(spec.scope):
        raise McpToolScopeMissingError(required=spec.scope, tool=name)
    # Checked after the scope so an environment without the runtime layer does
    # not become a way to probe which tools exist behind scopes you lack.
    if spec.requires_app_runtime and not app_runtime_enabled():
        raise AppPublishRuntimeLayerDisabledError()
    return spec


__all__ = [
    "CATEGORY_APP_DATA",
    "CATEGORY_APP_STATE",
    "CATEGORY_IDENTITY",
    "CATEGORY_KNOWLEDGE_LIST",
    "CATEGORY_KNOWLEDGE_SEARCH",
    "CATEGORY_MODEL_LIST",
    "TOOLS_BY_NAME",
    "TOOL_REGISTRY",
    "McpToolSpec",
    "app_runtime_enabled",
    "installed_tools",
    "require_tool",
    "visible_tools",
]
