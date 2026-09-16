"""Contract of the unified retrieval facade (F052 design §4.2 ③).

Data structures and constants only — the behaviour lives in
``knowledge/domain/services/retrieval_facade_service.py``. Four callers share
this contract: the MCP search tool, v2 ``POST /filelib/retrieve``, the F055
hosted runtime and the F057 SDK ``retrieve``.

The one idea worth stating here: **the facade knows nothing about its caller.**
It sees an execution identity and an optional declared whitelist, and it filters
to the same strength for every identity. "Who is asking" is not an input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL
from bisheng.permission.application.identity import (
    get_current_permission_actor,
    reset_current_permission_actor,
    resolve_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, typing only
    from bisheng.open_api.domain.context import OpenApiPrincipal

# Document knowledge bases (库级 filtering) and knowledge spaces (文件级).
# QA (1) and the retired personal KB (2) answer "unreachable" on the retrieval
# face — see spec 决议-10; they are *not* reported as "unsupported type",
# because a distinguishable answer would leak existence.
SUPPORTED_KNOWLEDGE_TYPES: frozenset[int] = frozenset({KnowledgeTypeEnum.NORMAL.value, KnowledgeTypeEnum.SPACE.value})

#: Hard caps. ``RETRIEVAL_TOP_K_MAX`` matches ``RetrieveReq.top_k``'s ``le`` so
#: the v2 contract can never trip the clamp.
RETRIEVAL_TOP_K_MAX = 200
RETRIEVAL_MAX_CONTENT_MAX = 60000
RETRIEVAL_TARGETS_MAX = 50
RETRIEVAL_SCOPE_MAX = 200


@dataclass(frozen=True)
class RetrievalIdentity:
    """Who the retrieval runs as. Never "who called the facade"."""

    actor: PermissionActor
    login_user: UserPayload

    @classmethod
    def from_open_api_principal(cls, principal: OpenApiPrincipal) -> RetrievalIdentity:
        """Build the identity of an open-API credential's subject.

        Mode S resolves to the credential subject itself (service account or
        the natural person behind a personal token); mode D resolves to the
        represented user. Deliberately does **not** go through
        ``get_open_api_operator_async`` — that helper spends a Redis and an FGA
        round trip re-deriving administrator facts the gate already resolved,
        on a face that is called once per retrieval (design 坑 8).

        The administrator facts and the F066 ``data_scope`` are taken from the
        actor the gate already installed, never re-derived and never assumed
        (design 坑 8 / K4). Rebuilding a bare actor here would silently answer
        ``data_scope=ALL`` for a narrowed personal token — the narrowing lives
        inside the permission runtime and is keyed off exactly this field, so a
        fresh actor **widens** what the credential can retrieve. The gate's
        actor is only adopted when it describes this very subject, so a caller
        outside the gate cannot inherit somebody else's privileges.
        """

        actor = None
        contextual = get_current_permission_actor()
        if (
            contextual is not None
            and contextual.subject_type == principal.authorization_subject_type
            and contextual.subject_id == principal.authorization_subject_id
            and contextual.tenant_id == principal.tenant_id
        ):
            actor = contextual
        if actor is None:
            actor = PermissionActor(
                subject_type=principal.authorization_subject_type,
                subject_id=principal.authorization_subject_id,
                tenant_id=principal.tenant_id,
                data_scope=DATA_SCOPE_ALL,
            )
        login_user = UserPayload(
            user_id=principal.effective_user_id or principal.actor_id,
            user_name=principal.actor_name,
            user_role=[],
            tenant_id=principal.tenant_id,
            is_global_super=False,
        )
        return cls(actor=actor, login_user=login_user)

    @classmethod
    async def from_user(
        cls,
        user_id: int,
        tenant_id: int,
        *,
        user_name: str = "",
        data_scope: str = DATA_SCOPE_ALL,
    ) -> RetrievalIdentity:
        """Build the identity of a platform user (F055 hosted runtime).

        Administrator facts are resolved through the permission layer rather
        than assumed, so a tenant administrator using a hosted app still gets
        the administrator shortcut on *visibility* — while the declared
        whitelist keeps narrowing the scope (AC-21).

        The ambient actor is cleared for the duration of that resolution.
        ``resolve_permission_actor`` returns the ContextVar's actor when there
        is one (design 坑 5), and every caller of this constructor reaches it
        *inside* an authenticated request — F055's hosted runtime calls it with
        the application's own credential actor installed. Without the reset the
        access user would silently be handed the application's visibility,
        which is the exact opposite of what AC-42 promises its users.
        """

        login_user = UserPayload(
            user_id=user_id,
            user_name=user_name,
            user_role=[],
            tenant_id=tenant_id,
            is_global_super=False,
        )
        token = set_current_permission_actor(None)
        try:
            actor = await resolve_permission_actor(login_user)
        finally:
            reset_current_permission_actor(token)
        if data_scope != actor.data_scope:
            actor = PermissionActor(
                subject_type=actor.subject_type,
                subject_id=actor.subject_id,
                tenant_id=actor.tenant_id,
                super_admin=actor.super_admin,
                tenant_admin_tenant_ids=actor.tenant_admin_tenant_ids,
                data_scope=data_scope,
            )
        return cls(actor=actor, login_user=login_user)


@dataclass(frozen=True)
class RetrievalRequest:
    """One retrieval. ``whitelist=None`` means "no declared scope at all"."""

    query: str
    knowledge_ids: list[int] | None = None
    whitelist: list[int] | None = None
    top_k: int = 10
    max_content: int = 15000
    tag_filters: dict[int, list[str]] | None = None


@dataclass(frozen=True)
class RetrievalChunk:
    knowledge_id: int
    knowledge_type: int
    knowledge_name: str
    document_id: int
    document_name: str
    chunk_index: int
    content: str
    document_update_time: str = ""


@dataclass(frozen=True)
class RetrievalFacadeResult:
    chunks: list[RetrievalChunk] = field(default_factory=list)
    total: int = 0
    effective_scope: list[int] = field(default_factory=list)
    #: Parameters the platform clamped, so the caller can surface the
    #: truncation instead of silently returning less than it asked for.
    truncated_params: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class AccessibleKnowledge:
    knowledge_id: int
    name: str
    type: str  # "library" | "space"
    description: str = ""


@dataclass(frozen=True)
class ReachabilityReport:
    reachable: list[int] = field(default_factory=list)
    unreachable: list[int] = field(default_factory=list)
    revoked: list[int] = field(default_factory=list)


def knowledge_type_label(knowledge_type: int) -> str:
    """Public wording for a supported knowledge type."""

    return "space" if knowledge_type == KnowledgeTypeEnum.SPACE.value else "library"


__all__ = [
    "RETRIEVAL_MAX_CONTENT_MAX",
    "RETRIEVAL_SCOPE_MAX",
    "RETRIEVAL_TARGETS_MAX",
    "RETRIEVAL_TOP_K_MAX",
    "SUPPORTED_KNOWLEDGE_TYPES",
    "AccessibleKnowledge",
    "ReachabilityReport",
    "RetrievalChunk",
    "RetrievalFacadeResult",
    "RetrievalIdentity",
    "RetrievalRequest",
    "knowledge_type_label",
]
