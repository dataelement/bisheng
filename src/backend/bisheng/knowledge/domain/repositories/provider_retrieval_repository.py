"""Read the scoped control facts for external retrieval; never fetch provider content."""

from dataclasses import dataclass

from sqlalchemy import exists, select

from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderBinding as B
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderGeneration as G
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance as I
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderMapping as M
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderTagRef as T


@dataclass(frozen=True)
class Route:
    tenant_id: int
    space_id: int
    provider_key: str
    generation: int
    instance_id: int
    remote_scope_id: str
    remote_kb_id: str
    capability_revision: int
    content_revision: int


class RetrievalFactsUnavailable(ValueError):
    """The selected space no longer has trusted routing or selection facts."""


class ProviderRetrievalRepository:
    def __init__(self, session=get_async_db_session):
        self.session = session

    async def route(self, space):
        tenant = get_current_tenant_id()
        if is_tenant_filter_bypassed():
            raise RetrievalFactsUnavailable("invalid retrieval tenant")
        if tenant is not None:
            # A resolved context that names another tenant is never a route.
            if type(tenant) is not int or tenant <= 0 or tenant != space.tenant_id:
                raise RetrievalFactsUnavailable("invalid retrieval tenant")
        else:
            # Context-less internal callers (worker / legacy paths) may only
            # discover whether THIS space is external; the space row itself came
            # from their own authorised read. External retrieval still fails
            # closed later in ``load_candidates`` when the tenant is unresolved.
            # A space object with no tenant fact cannot be external: there is no
            # tenant whose external access could be authorised.
            tenant = getattr(space, "tenant_id", None)
            if type(tenant) is not int or tenant <= 0:
                return None
        async with self.session() as session:
            row = (
                await session.execute(
                    select(B.provider_key, B.active_generation, B.state).where(
                        B.tenant_id == tenant, B.space_id == space.id
                    )
                )
            ).one_or_none()
            declared_key = getattr(space, "provider_key", None)
            if isinstance(declared_key, str) and declared_key != (row[0] if row is not None else "native"):
                raise RetrievalFactsUnavailable("provider binding mismatch")
            if row is None or tuple(row) == ("native", None, "ready"):
                return None  # Unbound legacy native space.
            key, gen, state = row
            if state != "ready" or key == "native" or not gen:
                raise RetrievalFactsUnavailable("provider binding unavailable")
            target = (
                await session.execute(
                    select(I.id, G.remote_scope_id, G.remote_kb_id, I.capability_revision, G.content_revision)
                    .select_from(G)
                    .join(I, I.id == G.provider_instance_id)
                    .where(
                        G.tenant_id == tenant,
                        G.space_id == space.id,
                        G.generation == gen,
                        G.state == "ready",
                        G.content_revision >= 0,
                        I.tenant_id == tenant,
                        I.provider_key == key,
                        I.remote_scope_id == G.remote_scope_id,
                        I.state == "ready",
                    )
                )
            ).one_or_none()
            if not target:
                raise RetrievalFactsUnavailable("provider instance unavailable")
            return Route(tenant, space.id, key, gen, *target)

    async def load_candidates(self, route, *, file_ids, tag_ref_ids):
        if get_current_tenant_id() != route.tenant_id or is_tenant_filter_bypassed():
            raise RetrievalFactsUnavailable("retrieval tenant changed")
        f, v, d = KnowledgeFile, KnowledgeDocumentVersion, KnowledgeDocument
        other = v.__table__.alias("other_file_version")
        unique_version = ~exists(
            select(other.c.id).where(other.c.knowledge_file_id == f.id, other.c.id != v.id)
        ).correlate(f, v)
        query = (
            select(
                M.remote_object_id,
                f.id,
                M.version_id,
                d.id,
                M.operation_epoch,
                M.ready_revision,
                f.file_name,
                v.version_no,
            )
            .select_from(M)
            .join(f, f.id == M.local_resource_id)
            .join(v, v.id == M.version_id)
            .join(d, d.id == M.logical_document_id)
            .where(
                M.tenant_id == route.tenant_id,
                M.space_id == route.space_id,
                M.generation == route.generation,
                M.resource_type == "file",
                M.lifecycle_state == "active",
                M.tombstoned_at.is_(None),
                M.ready_revision >= 0,
                M.ready_revision <= route.content_revision,
                f.tenant_id == route.tenant_id,
                f.knowledge_id == route.space_id,
                f.file_type == FileType.FILE.value,
                d.knowledge_id == route.space_id,
                d.primary_version_id == v.id,
                v.document_id == d.id,
                v.knowledge_file_id == f.id,
                v.is_primary.is_(True),
                v.version_no > 0,
                unique_version,
            )
        )
        async with self.session() as session:
            tags = []
            if tag_ref_ids:
                tags = (
                    (
                        await session.execute(
                            select(T.remote_tag_id).where(
                                T.tenant_id == route.tenant_id,
                                T.space_id == route.space_id,
                                T.generation == route.generation,
                                T.state == "active",
                                T.tag_ref_id.in_(tag_ref_ids),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(tags) != len(set(tag_ref_ids)):
                    raise RetrievalFactsUnavailable("stale provider tag selection")
            if file_ids is not None:
                query = query.where(f.id.in_(file_ids))
            rows = (await session.execute(query)).all()
        return rows, tags
