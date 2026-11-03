"""The unified retrieval facade (F052 design D5) — the open face's only way in.

Four callers share it: the MCP search tool, v2 ``POST /filelib/retrieve``, the
F055 hosted runtime and the F057 SDK ``retrieve``. It is deliberately session
decoupled — no ``Request``, no chat session, no message row — so "which caller
is this" is never an input to a permission decision.

What the facade adds on top of ``RetrievalEngine``:

* **Fail-closed identity.** No execution identity, no retrieval (AC-23). There
  is no fallback to a configured operator, a whitelist-wide grant, or a
  "public subset".
* **Reachability, decided in one batch before anything is retrieved.** A
  knowledge base that is missing, ungranted, or of an unsupported type gets
  *one* answer (26321). Distinguishing them would let a caller probe for the
  existence of knowledge bases it may not see.
* **Declared-scope narrowing.** With a whitelist the scope is
  ``whitelist ∩ visible``, and no identity — administrator included — reaches
  outside it (AC-21). A whitelisted knowledge base that has *disappeared* is a
  different matter and says so (26322), because F055 has to turn that into a
  visible "capability revoked" instead of quietly searching less.
* **Visible clamping.** Over-large ``top_k`` / ``max_content`` are clamped and
  the clamp is reported; an over-large scope is refused rather than truncated.

There is no caching here on purpose. Any visibility cache would have to answer
"what happens to the five-second revocation bound" (INV-28) and "what happens
when the permission engine is down" (INV-30) first — see design 坑 23.
"""

from __future__ import annotations

from loguru import logger

from bisheng.common.errcode.mcp_face import (
    KnowledgeCapabilityRevokedError,
    KnowledgeUnreachableError,
    RetrievalIdentityMissingError,
    RetrievalScopeTooLargeError,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.schemas.retrieval_facade import (
    RETRIEVAL_MAX_CONTENT_MAX,
    RETRIEVAL_SCOPE_MAX,
    RETRIEVAL_TARGETS_MAX,
    RETRIEVAL_TOP_K_MAX,
    SUPPORTED_KNOWLEDGE_TYPES,
    AccessibleKnowledge,
    ReachabilityReport,
    RetrievalChunk,
    RetrievalFacadeResult,
    RetrievalIdentity,
    RetrievalRequest,
    knowledge_type_label,
)
from bisheng.knowledge.domain.services.retrieval_engine import RetrievalEngine
from bisheng.permission.application.access import get_f048_runtime
from bisheng.permission.application.business_authorization import batch_check_business_actions
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL
from bisheng.permission.application.identity import (
    reset_current_permission_actor,
    set_current_permission_actor,
)

# Resource type ↔ gate action, matching the two in-platform paths exactly:
# a knowledge space is gated on ``visible``, a document library on ``use``.
# The names are the ones registered in the F048 resource registry.
_SPACE_RESOURCE_TYPE = "knowledge_space"
_LIBRARY_RESOURCE_TYPE = "knowledge_library"
_SPACE_ACTION = "visible"
_LIBRARY_ACTION = "use"


class _ScopeResolution:
    """Intermediate state shared by ``retrieve`` and ``check_reachable``."""

    __slots__ = ("declared", "revoked", "targets", "unreachable")

    def __init__(self) -> None:
        self.targets: list[int] = []
        self.unreachable: list[int] = []
        self.revoked: list[int] = []
        self.declared: bool = False


class RetrievalFacadeService:
    """Session-decoupled retrieval, filtered to one execution identity."""

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    @staticmethod
    def is_supported_knowledge_type(knowledge_type: int) -> bool:
        """Types the facade can retrieve from at all (文档知识库 + 知识空间)."""

        return knowledge_type in SUPPORTED_KNOWLEDGE_TYPES

    @classmethod
    async def retrieve(
        cls,
        identity: RetrievalIdentity | None,
        req: RetrievalRequest,
        *,
        version_repo=None,
    ) -> RetrievalFacadeResult:
        """Retrieve chunks as ``identity``, within ``req``'s (declared) scope."""

        cls._require_identity(identity)

        top_k, max_content, truncated = cls._clamp(req)

        token = set_current_permission_actor(identity.actor)
        try:
            resolution = cls._resolve_scope(req)
            if resolution.declared and not resolution.targets and not resolution.unreachable:
                # A declared-but-empty scope is F055's pre-check problem, not an
                # error here: the app simply has nothing wired up.
                return RetrievalFacadeResult(chunks=[], total=0, effective_scope=[], truncated_params=truncated)

            if not resolution.declared and not resolution.targets:
                # AC-22: no named targets and no declared scope means "everything
                # this identity was granted". Already visibility-filtered.
                reachable_rows = await cls._enumerate_accessible_rows(identity, strict_cap=True)
            else:
                rows = await cls._load_rows(resolution, explicit=bool(req.knowledge_ids))
                reachable_rows = await cls._filter_visible(
                    identity,
                    rows,
                    resolution,
                    explicit_ids=set(req.knowledge_ids or ()),
                )
                cls._raise_for_unreachable(resolution)
            if not reachable_rows:
                return RetrievalFacadeResult(chunks=[], total=0, effective_scope=[], truncated_params=truncated)

            engine = RetrievalEngine(identity.login_user, version_repo=version_repo)
            results = await engine.retrieve_many(
                reachable_rows,
                query=req.query,
                tag_filters=req.tag_filters,
                max_content=max_content,
            )
            results = results[:top_k]
            await engine.attach_document_update_time(results)
        finally:
            reset_current_permission_actor(token)

        rows_by_id = {row.id: row for row in reachable_rows}
        chunks = [cls._to_chunk(rows_by_id[knowledge_id], doc) for knowledge_id, doc in results]
        logger.info(
            "retrieval_facade | subject={}:{} scope_size={} chunks={} declared={}",
            identity.actor.subject_type,
            identity.actor.subject_id,
            len(reachable_rows),
            len(chunks),
            resolution.declared,
        )
        return RetrievalFacadeResult(
            chunks=chunks,
            total=len(chunks),
            effective_scope=[row.id for row in reachable_rows],
            truncated_params=truncated,
        )

    @classmethod
    async def list_accessible_knowledge(
        cls,
        identity: RetrievalIdentity | None,
        *,
        name: str | None = None,
        limit: int = RETRIEVAL_SCOPE_MAX,
    ) -> list[AccessibleKnowledge]:
        """Knowledge bases this identity may retrieve from, supported types only."""

        cls._require_identity(identity)

        token = set_current_permission_actor(identity.actor)
        try:
            rows = await cls._enumerate_accessible_rows(identity)
        finally:
            reset_current_permission_actor(token)

        if name:
            needle = name.strip().lower()
            rows = [row for row in rows if needle in (row.name or "").lower()]
        return [
            AccessibleKnowledge(
                knowledge_id=row.id,
                name=row.name or "",
                type=knowledge_type_label(row.type),
                description=row.description or "",
            )
            for row in rows[:limit]
        ]

    @classmethod
    async def check_reachable(
        cls,
        identity: RetrievalIdentity | None,
        knowledge_ids: list[int],
        *,
        whitelist: list[int] | None = None,
    ) -> ReachabilityReport:
        """Split ``knowledge_ids`` into reachable / unreachable / revoked.

        Runs every reachability decision ``retrieve`` runs and none of the
        retrieval, so F055's declaration pre-check and the facade can never
        disagree about what "reachable" means.
        """

        cls._require_identity(identity)

        req = RetrievalRequest(query="", knowledge_ids=list(knowledge_ids), whitelist=whitelist)
        token = set_current_permission_actor(identity.actor)
        try:
            resolution = cls._resolve_scope(req)
            rows = await cls._load_rows(resolution, explicit=True, collect_revoked=True)
            reachable_rows = await cls._filter_visible(
                identity,
                rows,
                resolution,
                explicit_ids=set(knowledge_ids),
            )
        finally:
            reset_current_permission_actor(token)

        return ReachabilityReport(
            reachable=[row.id for row in reachable_rows],
            unreachable=sorted(set(resolution.unreachable)),
            revoked=sorted(set(resolution.revoked)),
        )

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    @staticmethod
    def _require_identity(identity: RetrievalIdentity | None) -> None:
        """AC-23: an unresolvable identity is a refusal, never a default."""

        if identity is None or identity.actor is None or not getattr(identity.actor, "subject_id", None):
            raise RetrievalIdentityMissingError()

    @staticmethod
    def _clamp(req: RetrievalRequest) -> tuple[int, int, dict[str, int]]:
        truncated: dict[str, int] = {}
        top_k = min(req.top_k, RETRIEVAL_TOP_K_MAX)
        if top_k != req.top_k:
            truncated["top_k"] = top_k
        max_content = min(req.max_content, RETRIEVAL_MAX_CONTENT_MAX)
        if max_content != req.max_content:
            truncated["max_content"] = max_content
        return top_k, max_content, truncated

    @classmethod
    def _resolve_scope(cls, req: RetrievalRequest) -> _ScopeResolution:
        """Decide which knowledge ids this request is even about.

        Note what is *not* here: the full-scope enumeration. Resolving "no
        targets, no whitelist" needs an await, so it happens in ``_load_rows``.
        """

        resolution = _ScopeResolution()
        targets = list(dict.fromkeys(req.knowledge_ids or ()))

        if req.whitelist is not None:
            resolution.declared = True
            allowed = set(req.whitelist)
            if targets:
                resolution.targets = [one for one in targets if one in allowed]
                resolution.unreachable = [one for one in targets if one not in allowed]
            else:
                resolution.targets = list(dict.fromkeys(req.whitelist))
        else:
            resolution.targets = targets

        if len(resolution.targets) > RETRIEVAL_TARGETS_MAX:
            raise RetrievalScopeTooLargeError(limit=RETRIEVAL_TARGETS_MAX)
        return resolution

    @classmethod
    async def _load_rows(
        cls,
        resolution: _ScopeResolution,
        *,
        explicit: bool,
        collect_revoked: bool = False,
    ) -> list:
        """Load the knowledge rows, sorting missing / unsupported ids as we go."""

        if not resolution.targets and not resolution.declared:
            return []

        rows = await KnowledgeDao.aget_list_by_ids(list(resolution.targets))
        by_id = {row.id: row for row in rows}

        kept: list = []
        for knowledge_id in resolution.targets:
            row = by_id.get(knowledge_id)
            supported = row is not None and cls.is_supported_knowledge_type(row.type)
            if supported:
                kept.append(row)
                continue
            if resolution.declared:
                # AC-46: a declared knowledge base that is gone is a capability
                # that was revoked, not a scope the app should silently shrink.
                resolution.revoked.append(knowledge_id)
                if not collect_revoked:
                    raise KnowledgeCapabilityRevokedError(knowledge_id=knowledge_id)
            elif explicit:
                resolution.unreachable.append(knowledge_id)
        return kept

    @classmethod
    async def _filter_visible(
        cls,
        identity: RetrievalIdentity,
        rows: list,
        resolution: _ScopeResolution,
        *,
        explicit_ids: set[int],
    ) -> list:
        """One batch check per resource type; never one round trip per target."""

        if not rows:
            return []

        spaces = [row for row in rows if row.type == KnowledgeTypeEnum.SPACE.value]
        libraries = [row for row in rows if row.type == KnowledgeTypeEnum.NORMAL.value]

        space_actions: dict[str, frozenset[str]] = {}
        library_actions: dict[str, frozenset[str]] = {}
        if spaces:
            space_actions = await batch_check_business_actions(
                identity.login_user,
                resource_type=_SPACE_RESOURCE_TYPE,
                resource_ids=[row.id for row in spaces],
                actions=(_SPACE_ACTION,),
            )
        if libraries:
            library_actions = await batch_check_business_actions(
                identity.login_user,
                resource_type=_LIBRARY_RESOURCE_TYPE,
                resource_ids=[row.id for row in libraries],
                actions=(_LIBRARY_ACTION,),
            )

        visible: list = []
        for row in rows:
            if row.type == KnowledgeTypeEnum.SPACE.value:
                allowed = _SPACE_ACTION in space_actions.get(str(row.id), frozenset())
            else:
                allowed = _LIBRARY_ACTION in library_actions.get(str(row.id), frozenset())
            if allowed:
                visible.append(row)
            elif row.id in explicit_ids:
                # Named but invisible answers exactly like "does not exist".
                resolution.unreachable.append(row.id)
            # A declared-but-invisible knowledge base simply drops out (AC-21).
        return visible

    @staticmethod
    def _raise_for_unreachable(resolution: _ScopeResolution) -> None:
        if resolution.unreachable:
            raise KnowledgeUnreachableError(unreachable_ids=sorted(set(resolution.unreachable)))

    @classmethod
    async def _enumerate_accessible_rows(cls, identity: RetrievalIdentity, *, strict_cap: bool = False) -> list:
        """Everything this identity may retrieve from, both supported types.

        ``strict_cap`` is what separates the two callers: a retrieval over an
        unnamed scope must **refuse** a scope it cannot enumerate completely
        (26323 — "name the knowledge bases explicitly"), because silently
        searching the first 200 would look like a complete answer. The listing
        tool simply pages.
        """

        actor = identity.actor
        is_admin = actor.super_admin or actor.current_tenant_id in actor.tenant_admin_tenant_ids
        if actor.data_scope != DATA_SCOPE_ALL:
            # F066 坑 7: a narrowed token never takes the administrator bypass —
            # the narrowing is enforced inside the permission runtime, so the
            # enumeration must actually reach it.
            is_admin = False

        if is_admin:
            rows: list = []
            for knowledge_type in (KnowledgeTypeEnum.SPACE, KnowledgeTypeEnum.NORMAL):
                # Tenant-scoped by the automatic filter (C3); one page beyond the
                # cap so an over-wide scope is detected rather than truncated.
                rows.extend(
                    await KnowledgeDao.aget_all_knowledge(
                        None,
                        knowledge_type,
                        limit=RETRIEVAL_SCOPE_MAX + 1,
                    )
                )
            rows = [row for row in rows if cls.is_supported_knowledge_type(row.type)]
            if strict_cap and len(rows) > RETRIEVAL_SCOPE_MAX:
                raise RetrievalScopeTooLargeError(limit=RETRIEVAL_SCOPE_MAX)
            return rows

        runtime = await get_f048_runtime()
        candidate_ids: list[int] = []
        for resource_type in (_SPACE_RESOURCE_TYPE, _LIBRARY_RESOURCE_TYPE):
            visible = await runtime.list_visible_objects(
                actor,
                resource_type=resource_type,
                max_results=RETRIEVAL_SCOPE_MAX,
            )
            candidate_ids.extend(int(object_id) for object_id in visible.object_ids)

        candidate_ids = list(dict.fromkeys(candidate_ids))
        if strict_cap and len(candidate_ids) > RETRIEVAL_SCOPE_MAX:
            raise RetrievalScopeTooLargeError(limit=RETRIEVAL_SCOPE_MAX)
        if not candidate_ids:
            return []
        rows = await KnowledgeDao.aget_list_by_ids(candidate_ids)
        rows = [row for row in rows if cls.is_supported_knowledge_type(row.type)]

        # ``visible`` enumeration is a superset of the concrete gates, so confirm.
        resolution = _ScopeResolution()
        return await cls._filter_visible(identity, rows, resolution, explicit_ids=set())

    @staticmethod
    def _to_chunk(row, doc) -> RetrievalChunk:
        metadata = doc.metadata or {}
        return RetrievalChunk(
            knowledge_id=row.id,
            knowledge_type=row.type,
            knowledge_name=row.name or "",
            document_id=int(metadata.get("document_id", 0)),
            document_name=str(metadata.get("document_name", "")),
            chunk_index=int(metadata.get("chunk_index", 0)),
            content=doc.page_content,
            document_update_time=str(metadata.get("document_update_time", "")),
        )


__all__ = ["RetrievalFacadeService"]
