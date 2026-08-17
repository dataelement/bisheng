"""``OPEN_API_SCOPES`` registry + ``@open_api_scope`` endpoint marker (F049 design D3 / D9).

The registry is the **single source of truth** for scope codes: the issue /
edit forms (``GET /api/v1/service-accounts/scopes``), issue-time validation,
the router-level ``/api/v2`` dependency and F051-F053 runtime checks all read
it. Scopes are code constants, not rows - a table would only drift (D9).

Endpoint marking (D3): every ``/api/v2`` endpoint function carries
``@open_api_scope("<code>")`` (or ``@open_api_scope(None)`` for the few
credential-only endpoints such as ``/api/v2/auth/whoami``). The router-level
dependency reads the marker off ``conn.scope["endpoint"]``:

* no marker            -> 26031 (unregistered endpoint, structural fail-closed)
* marker ``scope=None`` -> credential check only, no scope check
* marker with a code   -> the credential must hold that scope, else 26003

The decorator only sets a function attribute - no FastAPI import - so v2
endpoint files can import it without touching another module's ``api/`` layer
(arch RULE-5).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# i18n keys below are relative to the platform ``serviceAccount`` namespace
# (``platform/public/locales/*/serviceAccount.json``, T028+); the backend never
# ships copy for them (design §4.3 "不含 UI 文案").

GROUP_WORKFLOW = "workflow"
GROUP_ASSISTANT = "assistant"
GROUP_KNOWLEDGE = "knowledge"
GROUP_LOCAL_DEV_TOOLKIT = "local_dev_toolkit"

# HTTP method pseudo-value for WebSocket routes in ``endpoints``.
WS = "WS"


@dataclass(frozen=True)
class OpenApiScope:
    """One scope registry entry (design D9)."""

    code: str
    group: str
    label_key: str
    desc_key: str
    # ``(method, path)`` pairs this scope unlocks - informational (issue-form
    # hover, AC-44) and consumed by the D3 route-completeness test. ``()`` for
    # scopes whose endpoints ship in a later version (``chat:invoke``) and for
    # the toolkit scopes whose surfaces are separate routers (F051-F053).
    endpoints: tuple[tuple[str, str], ...] = ()
    # True -> only offered / accepted while ``settings.open_platform.enabled``
    # (AC-13); a request carrying it otherwise is rejected with 26023.
    requires_open_platform: bool = False
    # Set when the scope is issuable but its endpoints are not open yet; the
    # form shows the note instead of an endpoint list (spec: "端点随后续版本开放").
    pending_note_key: str | None = None
    # Extra hint keys the form renders (e.g. identity:read full-org warning).
    hint_keys: tuple[str, ...] = field(default_factory=tuple)


_V2 = "/api/v2"

OPEN_API_SCOPES: tuple[OpenApiScope, ...] = (
    OpenApiScope(
        code="workflow:invoke",
        group=GROUP_WORKFLOW,
        label_key="scopes.workflow_invoke.label",
        desc_key="scopes.workflow_invoke.desc",
        endpoints=(
            ("POST", f"{_V2}/workflow/invoke"),
            ("POST", f"{_V2}/workflow/stop"),
            (WS, f"{_V2}/workflow/chat/{{workflow_id}}"),
        ),
    ),
    OpenApiScope(
        code="workflow:read",
        group=GROUP_WORKFLOW,
        label_key="scopes.workflow_read.label",
        desc_key="scopes.workflow_read.desc",
        endpoints=(("GET", f"{_V2}/flows/{{flow_id}}"),),
    ),
    OpenApiScope(
        code="assistant:invoke",
        group=GROUP_ASSISTANT,
        label_key="scopes.assistant_invoke.label",
        desc_key="scopes.assistant_invoke.desc",
        endpoints=(
            ("POST", f"{_V2}/assistant/chat/completions"),
            (WS, f"{_V2}/assistant/chat/{{assistant_id}}"),
            ("POST", f"{_V2}/llm/workbench/asr"),
            ("POST", f"{_V2}/llm/workbench/tts"),
        ),
    ),
    OpenApiScope(
        code="assistant:read",
        group=GROUP_ASSISTANT,
        label_key="scopes.assistant_read.label",
        desc_key="scopes.assistant_read.desc",
        endpoints=(
            ("GET", f"{_V2}/assistant/list"),
            ("GET", f"{_V2}/assistant/info/{{assistant_id}}"),
        ),
    ),
    OpenApiScope(
        code="chat:invoke",
        group=GROUP_ASSISTANT,
        label_key="scopes.chat_invoke.label",
        desc_key="scopes.chat_invoke.desc",
        # Issuable and persisted today; endpoints arrive with F058 (Responses
        # contract). F058 adds the markers and clears ``pending_note_key``.
        endpoints=(),
        pending_note_key="scopes.chat_invoke.pending_note",
    ),
    OpenApiScope(
        code="knowledge:read",
        group=GROUP_KNOWLEDGE,
        label_key="scopes.knowledge_read.label",
        desc_key="scopes.knowledge_read.desc",
        endpoints=(
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
        code="knowledge:write",
        group=GROUP_KNOWLEDGE,
        label_key="scopes.knowledge_write.label",
        desc_key="scopes.knowledge_write.desc",
        endpoints=(
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
    # --- local dev toolkit (open platform only; F051 / F052 / F053 consume) ---
    OpenApiScope(
        code="model:invoke",
        group=GROUP_LOCAL_DEV_TOOLKIT,
        label_key="scopes.model_invoke.label",
        desc_key="scopes.model_invoke.desc",
        requires_open_platform=True,
    ),
    OpenApiScope(
        code="identity:read",
        group=GROUP_LOCAL_DEV_TOOLKIT,
        label_key="scopes.identity_read.label",
        desc_key="scopes.identity_read.desc",
        requires_open_platform=True,
        hint_keys=("scopes.identity_read.full_org_warning",),
    ),
    OpenApiScope(
        code="app:manage",
        group=GROUP_LOCAL_DEV_TOOLKIT,
        label_key="scopes.app_manage.label",
        desc_key="scopes.app_manage.desc",
        requires_open_platform=True,
        hint_keys=("scopes.app_manage.deploy_hint",),
    ),
)
# NOTE: ``delegate`` is deliberately NOT registered (AC-14, decision-6 f) - it
# ships with F050. Until then any request carrying it is rejected with 26024.

OPEN_API_SCOPE_MAP: dict[str, OpenApiScope] = {scope.code: scope for scope in OPEN_API_SCOPES}
OPEN_API_SCOPE_CODES: frozenset[str] = frozenset(OPEN_API_SCOPE_MAP)
LOCAL_DEV_TOOLKIT_SCOPES: frozenset[str] = frozenset(
    scope.code for scope in OPEN_API_SCOPES if scope.group == GROUP_LOCAL_DEV_TOOLKIT
)
# Reserved for F050 - recognised so the rejection can be specific (26024, not 26025).
DELEGATE_SCOPE_CODE = "delegate"

# Static consistency guard: the 38 endpoints of design D3 (3+1+4+2+7+21).
_MAPPED_ENDPOINTS = [ep for scope in OPEN_API_SCOPES for ep in scope.endpoints]
assert len(_MAPPED_ENDPOINTS) == 38, len(_MAPPED_ENDPOINTS)
assert len(set(_MAPPED_ENDPOINTS)) == 38, "an endpoint is mapped to two scopes"


def visible_scopes(open_platform_enabled: bool) -> tuple[OpenApiScope, ...]:
    """Scopes offered by the issue / edit form and accepted at validation (AC-13 / AC-49)."""
    if open_platform_enabled:
        return OPEN_API_SCOPES
    return tuple(scope for scope in OPEN_API_SCOPES if not scope.requires_open_platform)


def is_known_scope(code: str) -> bool:
    return code in OPEN_API_SCOPE_CODES


def is_toolkit_scope(code: str) -> bool:
    return code in LOCAL_DEV_TOOLKIT_SCOPES


# ---------------------------------------------------------------------------
# Endpoint marker
# ---------------------------------------------------------------------------

OPEN_API_SCOPE_ATTR = "__open_api_scope__"


@dataclass(frozen=True)
class OpenApiScopeMarker:
    """What ``@open_api_scope`` pins onto an endpoint function."""

    scope: str | None
    # WS endpoints that also accept ``?share_token=`` (design D8) - the router
    # dependency consults this before trying the share-token branch.
    allow_share_token: bool = False


def open_api_scope(
    scope: str | None, *, allow_share_token: bool = False
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a ``/api/v2`` endpoint with the scope it requires (``None`` = credential only).

    Pure marker: sets ``func.__open_api_scope__``; nothing else. Unknown codes
    fail at import time so a typo cannot silently become "no scope required".
    """
    if scope is not None and scope not in OPEN_API_SCOPE_CODES:
        raise ValueError(f"unknown open API scope {scope!r}; register it in OPEN_API_SCOPES first")
    marker = OpenApiScopeMarker(scope=scope, allow_share_token=allow_share_token)

    def _decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, OPEN_API_SCOPE_ATTR, marker)
        return func

    return _decorate


def get_open_api_scope_marker(endpoint: Any) -> OpenApiScopeMarker | None:
    """Read the marker back from a route endpoint (``conn.scope["endpoint"]``); ``None`` if unmarked."""
    marker = getattr(endpoint, OPEN_API_SCOPE_ATTR, None)
    return marker if isinstance(marker, OpenApiScopeMarker) else None
