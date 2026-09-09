"""Open API scope registry and fail-closed endpoint marker."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

IdentityMode = Literal["S", "D"]
WS = "WS"


@dataclass(frozen=True, slots=True)
class OpenApiScope:
    code: str
    endpoints: tuple[tuple[str, str], ...]
    issuable: bool = True


_V2 = "/api/v2"
OPEN_API_SCOPES: tuple[OpenApiScope, ...] = (
    OpenApiScope(
        "workflow:invoke",
        (
            ("POST", f"{_V2}/workflow/invoke"),
            ("POST", f"{_V2}/workflow/stop"),
            (WS, f"{_V2}/workflow/chat/{{workflow_id}}"),
        ),
    ),
    OpenApiScope("workflow:read", (("GET", f"{_V2}/flows/{{flow_id}}"),)),
    OpenApiScope(
        "assistant:invoke",
        (
            ("POST", f"{_V2}/assistant/chat/completions"),
            (WS, f"{_V2}/assistant/chat/{{assistant_id}}"),
            ("POST", f"{_V2}/llm/workbench/asr"),
            ("POST", f"{_V2}/llm/workbench/tts"),
        ),
    ),
    OpenApiScope(
        "assistant:read",
        (
            ("GET", f"{_V2}/assistant/list"),
            ("GET", f"{_V2}/assistant/info/{{assistant_id}}"),
        ),
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
    ),
    OpenApiScope("model:invoke", (), issuable=False),
    OpenApiScope("identity:read", (), issuable=False),
    OpenApiScope("app:manage", (), issuable=False),
    OpenApiScope("delegate", (), issuable=True),
)

OPEN_API_SCOPE_MAP = {scope.code: scope for scope in OPEN_API_SCOPES}
OPEN_API_SCOPE_CODES = frozenset(OPEN_API_SCOPE_MAP)
ISSUABLE_OPEN_API_SCOPE_CODES = frozenset(scope.code for scope in OPEN_API_SCOPES if scope.issuable)

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
