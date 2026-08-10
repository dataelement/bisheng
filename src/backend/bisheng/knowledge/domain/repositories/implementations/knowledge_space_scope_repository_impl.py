from __future__ import annotations

import hashlib

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.knowledge.domain.repositories.interfaces.knowledge_space_scope_repository import (
    KnowledgeSpaceScopeRepository,
)


class KnowledgeSpaceScopeRepositoryImpl(
    BaseRepositoryImpl[KnowledgeSpaceScope, int],
    KnowledgeSpaceScopeRepository,
):
    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeSpaceScope)

    async def find_by_space_id(self, space_id: int) -> KnowledgeSpaceScope | None:
        result = await self.session.exec(
            select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == space_id)
        )
        return result.first()

    async def find_by_space_ids(self, space_ids: list[int]) -> list[KnowledgeSpaceScope]:
        if not space_ids:
            return []
        result = await self.session.exec(
            select(KnowledgeSpaceScope).where(
                col(KnowledgeSpaceScope.space_id).in_(
                    sorted({int(space_id) for space_id in space_ids if int(space_id) > 0})
                )
            )
        )
        return list(result.all())

    async def list_portal_candidates(self, *, tenant_id: int) -> list[KnowledgeSpaceScope]:
        result = await self.session.exec(
            select(KnowledgeSpaceScope)
            .where(KnowledgeSpaceScope.tenant_id == tenant_id)
            .order_by(KnowledgeSpaceScope.space_id.asc())
        )
        return list(result.all())

    async def set_portal_discovery_enabled(
        self,
        *,
        space_id: int,
        enabled: bool,
    ) -> KnowledgeSpaceScope:
        result = await self.session.exec(
            select(KnowledgeSpaceScope)
            .where(KnowledgeSpaceScope.space_id == space_id)
            .with_for_update()
        )
        scope = result.first()
        if scope is None:
            raise ValueError(f"KnowledgeSpaceScope not found for space_id={space_id}")
        scope.portal_discovery_enabled = bool(enabled)
        self.session.add(scope)
        await self.session.commit()
        await self.session.refresh(scope)
        return scope

    async def stage_space_and_portal_discovery(
        self,
        *,
        space: Knowledge,
        enabled: bool,
    ) -> KnowledgeSpaceScope:
        result = await self.session.exec(
            select(KnowledgeSpaceScope)
            .where(KnowledgeSpaceScope.space_id == int(space.id))
            .with_for_update()
        )
        scope = result.first()
        if scope is None:
            raise ValueError(f"KnowledgeSpaceScope not found for space_id={space.id}")
        scope.portal_discovery_enabled = bool(enabled)
        self.session.add(space)
        self.session.add(scope)
        return scope

    async def update_space_and_portal_discovery(
        self,
        *,
        space: Knowledge,
        enabled: bool,
        department_binding: DepartmentKnowledgeSpace | None = None,
    ) -> KnowledgeSpaceScope:
        try:
            scope = await self.stage_space_and_portal_discovery(
                space=space,
                enabled=enabled,
            )
            if department_binding is not None:
                self.session.add(department_binding)
            await self.session.flush()
            await self.session.commit()
            await self.session.refresh(space)
            await self.session.refresh(scope)
            if department_binding is not None:
                await self.session.refresh(department_binding)
            return scope
        except Exception:
            await self.session.rollback()
            raise

    @staticmethod
    def build_discovery_snapshot(
        *,
        scopes: list[tuple[str, int, bool]],
        explicit_space_ids: list[int],
        explicit_file_ids: list[int],
    ) -> str:
        parts = [
            *(
                f"scope:{kind}:{space_id}:{int(enabled)}"
                for kind, space_id, enabled in sorted(
                    (str(kind), int(space_id), bool(enabled))
                    for kind, space_id, enabled in scopes
                )
            ),
            *(f"space:{space_id}" for space_id in sorted({int(item) for item in explicit_space_ids})),
            *(f"file:{file_id}" for file_id in sorted({int(item) for item in explicit_file_ids})),
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
