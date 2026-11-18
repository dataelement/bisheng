"""Cleanup exact superseded collections captured in the model change transaction."""

import re
from types import SimpleNamespace

from sqlmodel import select

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.background_execution import get_current_background_task
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_processing_fence import KnowledgeProcessingFence
from bisheng.knowledge.domain.models.knowledge_vector_cleanup import KnowledgeVectorCleanup as Cleanup


class RebuildCleanupRepository:
    @staticmethod
    def _tenant(*, background=True):
        tenant, proof = get_current_tenant_id(), get_current_background_task()
        if type(tenant) is not int or tenant <= 0 or (background and (proof is None or proof.tenant_id != tenant)):
            raise ResourceReferenceInvalidError(reason="rebuild_cleanup_background_required")
        return tenant

    async def acandidates(self, session, *, after=None):
        self._tenant(background=False)
        query = select(Cleanup.id).where(Cleanup.state == "pending")
        if after:
            query = query.where(Cleanup.id > after)
        with strict_tenant_filter():
            return tuple((await session.exec(query.order_by(Cleanup.id).limit(100))).all())

    async def aread(self, session, ident):
        tenant = self._tenant()
        with strict_tenant_filter():
            row = await session.get(Cleanup, ident)
            if row is None or row.tenant_id != tenant or row.state != "pending":
                return None
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,254}", row.collection_name) is None:
                raise ResourceReferenceInvalidError(reason="rebuild_cleanup_collection_invalid")
            file_ids = (
                await session.exec(
                    select(KnowledgeProcessingFence.file_id).where(
                        KnowledgeProcessingFence.space_id == row.space_id,
                    )
                )
            ).all()
        # Names are storage-global. Do not delete a legacy shared collection
        # while any resource still uses it; no tenant/resource data is returned.
        with bypass_tenant_filter():
            used = (
                await session.exec(
                    select(Knowledge.id).where(Knowledge.collection_name == row.collection_name).limit(1)
                )
            ).first()
        if used is not None:
            return None
        return SimpleNamespace(
            id=row.id,
            space_id=row.space_id,
            name=row.collection_name,
            manifest={"file_ids": [value for value in file_ids if value]},
        )

    async def amark(self, session, material, *, error_type=None):
        tenant = self._tenant()
        with strict_tenant_filter():
            row = (await session.exec(select(Cleanup).where(Cleanup.id == material.id).with_for_update())).one_or_none()
        if row is None or row.tenant_id != tenant or row.collection_name != material.name:
            raise ResourceReferenceInvalidError(reason="rebuild_cleanup_origin_changed")
        row.attempts += 1
        row.error_type = error_type
        row.state = "pending" if error_type else "completed"
        await session.flush()
