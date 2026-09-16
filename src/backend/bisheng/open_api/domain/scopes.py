"""Open API scope registry and fail-closed endpoint marker."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from bisheng.common.services.config_service import settings

IdentityMode = Literal["S", "D"]
WS = "WS"

GROUP_LOCAL_DEV_TOOLKIT = "local_dev_toolkit"
DELEGATE_SCOPE_CODE = "delegate"


@dataclass(frozen=True, slots=True)
class OpenApiScope:
    code: str
    endpoints: tuple[tuple[str, str], ...]
    group: str
    label_key: str
    desc_key: str
    # ``False`` -> never offered nor accepted at issue time, whatever the
    # deployment switches say: the surface it unlocks has not shipped yet
    # (``identity:read`` waits for F052).
    issuable: bool = True
    # ``True`` -> offered / accepted only while ``settings.open_platform.enabled``
    # (伴生 PRD §4.2.4 三扩展位; migration plan M7). Read per call through
    # ``is_scope_issuable`` so a deployment flag never freezes into an
    # import-time constant.
    requires_open_platform: bool = False
    hint_keys: tuple[str, ...] = ()


_V2 = "/api/v2"
OPEN_API_SCOPES: tuple[OpenApiScope, ...] = (
    OpenApiScope(
        "workflow:invoke",
        (
            ("POST", f"{_V2}/workflow/invoke"),
            ("POST", f"{_V2}/workflow/stop"),
            (WS, f"{_V2}/workflow/chat/{{workflow_id}}"),
        ),
        "workflow",
        "openApiManagement.scopes.workflow_invoke.label",
        "openApiManagement.scopes.workflow_invoke.desc",
    ),
    OpenApiScope(
        "workflow:read",
        (("GET", f"{_V2}/flows/{{flow_id}}"),),
        "workflow",
        "openApiManagement.scopes.workflow_read.label",
        "openApiManagement.scopes.workflow_read.desc",
    ),
    OpenApiScope(
        "assistant:invoke",
        (
            ("POST", f"{_V2}/assistant/chat/completions"),
            (WS, f"{_V2}/assistant/chat/{{assistant_id}}"),
            ("POST", f"{_V2}/llm/workbench/asr"),
            ("POST", f"{_V2}/llm/workbench/tts"),
        ),
        "assistant",
        "openApiManagement.scopes.assistant_invoke.label",
        "openApiManagement.scopes.assistant_invoke.desc",
    ),
    OpenApiScope(
        "assistant:read",
        (
            ("GET", f"{_V2}/assistant/list"),
            ("GET", f"{_V2}/assistant/info/{{assistant_id}}"),
        ),
        "assistant",
        "openApiManagement.scopes.assistant_read.label",
        "openApiManagement.scopes.assistant_read.desc",
    ),
    OpenApiScope(
        "chat:invoke",
        (
            ("POST", f"{_V2}/workstation/chat/completions"),
            ("GET", f"{_V2}/workstation/config"),
            ("GET", f"{_V2}/chat/list"),
            ("POST", f"{_V2}/knowledge/upload"),
            ("GET", f"{_V2}/chat/info"),
        ),
        "assistant",
        "openApiManagement.scopes.chat_invoke.label",
        "openApiManagement.scopes.chat_invoke.desc",
    ),
    OpenApiScope(
        "knowledge:read",
        (
            ("GET", f"{_V2}/filelib/"),
            ("GET", f"{_V2}/filelib/file/list"),
            ("POST", f"{_V2}/filelib/retrieve"),
            ("GET", f"{_V2}/filelib/download_statistic"),
            ("GET", f"{_V2}/filelib/detail_qa"),
            ("POST", f"{_V2}/filelib/query_qa"),
            ("GET", f"{_V2}/citation/{{citation_id}}"),
        ),
        "knowledge",
        "openApiManagement.scopes.knowledge_read.label",
        "openApiManagement.scopes.knowledge_read.desc",
    ),
    OpenApiScope(
        "knowledge:write",
        (
            ("POST", f"{_V2}/filelib/"),
            ("PUT", f"{_V2}/filelib/"),
            ("DELETE", f"{_V2}/filelib/{{knowledge_id}}"),
            ("DELETE", f"{_V2}/filelib/clear/{{knowledge_id}}"),
            ("POST", f"{_V2}/filelib/file/{{knowledge_id}}"),
            ("DELETE", f"{_V2}/filelib/file/{{file_id}}"),
            ("POST", f"{_V2}/filelib/delete_file"),
            ("POST", f"{_V2}/filelib/chunks"),
            ("POST", f"{_V2}/filelib/chunks_string"),
            ("POST", f"{_V2}/filelib/add_qa"),
            ("POST", f"{_V2}/filelib/add_relative_qa"),
            ("DELETE", f"{_V2}/filelib/qa/{{qa_id}}"),
            ("POST", f"{_V2}/filelib/update_qa"),
            ("POST", f"{_V2}/knowledge/add_metadata_fields"),
            ("PUT", f"{_V2}/knowledge/modify_metadata_fields"),
            ("DELETE", f"{_V2}/knowledge/delete_metadata_fields"),
            ("GET", f"{_V2}/knowledge/get_metadata_fields/{{knowledge_id}}"),
            ("POST", f"{_V2}/knowledge/file/add_user_metadata"),
            ("PUT", f"{_V2}/knowledge/file/modify_user_metadata"),
            ("DELETE", f"{_V2}/knowledge/file/delete_user_metadata"),
            ("POST", f"{_V2}/knowledge/file/list_user_metadata"),
        ),
        "knowledge",
        "openApiManagement.scopes.knowledge_write.label",
        "openApiManagement.scopes.knowledge_write.desc",
    ),
    # --- local dev toolkit: the three extension scopes of 伴生 PRD §4.2.4.
    # Mode S only and mutually exclusive with ``delegate`` (INV-31); the
    # exclusion is enforced at issue / edit time by CredentialService.
    OpenApiScope(
        "model:invoke",
        # F051 model protocol face: the two promised OpenAI-compatible endpoints
        # plus the catch-all that refuses everything else. The catch-all is
        # registered too because it is a real mounted route and carries the same
        # marker — credentials are judged before the path is.
        (
            ("POST", f"{_V2}/model/v1/chat/completions"),
            ("GET", f"{_V2}/model/v1/models"),
            ("GET", f"{_V2}/model/v1/{{rest}}"),
            ("POST", f"{_V2}/model/v1/{{rest}}"),
            ("PUT", f"{_V2}/model/v1/{{rest}}"),
            ("DELETE", f"{_V2}/model/v1/{{rest}}"),
            ("PATCH", f"{_V2}/model/v1/{{rest}}"),
        ),
        GROUP_LOCAL_DEV_TOOLKIT,
        "openApiManagement.scopes.model_invoke.label",
        "openApiManagement.scopes.model_invoke.desc",
        requires_open_platform=True,
    ),
    OpenApiScope(
        "identity:read",
        (),
        GROUP_LOCAL_DEV_TOOLKIT,
        "openApiManagement.scopes.identity_read.label",
        "openApiManagement.scopes.identity_read.desc",
        issuable=False,  # F052 MCP face not shipped
        requires_open_platform=True,
        hint_keys=("openApiManagement.scopes.identity_read.warning",),
    ),
    OpenApiScope(
        "app:manage",
        # F055 publish pipeline: what ``bisheng deploy`` / ``bisheng logs`` call
        # (app_publish/api/endpoints/deploy.py, router prefix ``/apps``).
        (
            ("GET", f"{_V2}/apps/deploy-limits"),
            ("POST", f"{_V2}/apps/deploy"),
            ("GET", f"{_V2}/apps/deployments/{{deployment_id}}"),
            ("GET", f"{_V2}/apps/{{app_id}}/logs"),
        ),
        GROUP_LOCAL_DEV_TOOLKIT,
        "openApiManagement.scopes.app_manage.label",
        "openApiManagement.scopes.app_manage.desc",
        requires_open_platform=True,
        hint_keys=("openApiManagement.scopes.app_manage.hint",),
    ),
    OpenApiScope(
        DELEGATE_SCOPE_CODE,
        (),
        "delegation",
        "openApiManagement.scopes.delegate.label",
        "openApiManagement.scopes.delegate.desc",
        hint_keys=("openApiManagement.scopes.delegate.warning",),
    ),
)

OPEN_API_SCOPE_MAP = {scope.code: scope for scope in OPEN_API_SCOPES}
OPEN_API_SCOPE_CODES = frozenset(OPEN_API_SCOPE_MAP)
# The three extension scopes (伴生 PRD §4.2.4 / release-contract INV-31).
LOCAL_DEV_TOOLKIT_SCOPE_CODES = frozenset(
    scope.code for scope in OPEN_API_SCOPES if scope.group == GROUP_LOCAL_DEV_TOOLKIT
)
# Issuable on every deployment, no switch consulted. NOT the full issuable set:
# scopes gated by ``open_platform.enabled`` are only in ``issuable_scope_codes()``.
ALWAYS_ISSUABLE_OPEN_API_SCOPE_CODES = frozenset(
    scope.code for scope in OPEN_API_SCOPES if scope.issuable and not scope.requires_open_platform
)


def is_scope_issuable(scope: OpenApiScope) -> bool:
    """Whether this deployment may put ``scope`` on a credential right now."""
    if not scope.issuable:
        return False
    return not scope.requires_open_platform or bool(settings.open_platform.enabled)


def issuable_scopes() -> tuple[OpenApiScope, ...]:
    """Registry entries offered by the issue / edit form on this deployment."""
    return tuple(scope for scope in OPEN_API_SCOPES if is_scope_issuable(scope))


def issuable_scope_codes() -> frozenset[str]:
    """Codes accepted at issue / edit time on this deployment, evaluated per call."""
    return frozenset(scope.code for scope in issuable_scopes())


OPEN_API_SCOPE_ATTR = "__open_api_scope__"


@dataclass(frozen=True, slots=True)
class OpenApiScopeMarker:
    scope: str | None
    modes: frozenset[IdentityMode]
    session: bool


def open_api_scope(
    scope: str | None,
    *,
    modes: tuple[IdentityMode, ...] = ("S", "D"),
    session: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    if scope is not None and scope not in OPEN_API_SCOPE_CODES:
        raise ValueError(f"unknown open API scope {scope!r}")
    mode_set = frozenset(modes)
    if not mode_set or not mode_set <= {"S", "D"}:
        raise ValueError("modes must be a non-empty subset of {'S', 'D'}")
    marker = OpenApiScopeMarker(scope=scope, modes=mode_set, session=session)

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, OPEN_API_SCOPE_ATTR, marker)
        return func

    return decorate


def get_open_api_scope_marker(endpoint: Any) -> OpenApiScopeMarker | None:
    marker = getattr(endpoint, OPEN_API_SCOPE_ATTR, None)
    return marker if isinstance(marker, OpenApiScopeMarker) else None
