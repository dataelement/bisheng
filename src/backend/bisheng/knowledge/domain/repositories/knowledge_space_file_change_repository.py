from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_file_change_policy import (
    KnowledgeSpaceFileChangePolicy,
    KnowledgeSpaceFileChangeSetting,
)


@dataclass(frozen=True)
class KnowledgeSpaceFileChangeSettingRow:
    space: Knowledge
    setting: KnowledgeSpaceFileChangeSetting | None
    is_department: bool


class KnowledgeSpaceFileChangeRepository:
    """Session-bound persistence for F046 policy and per-space settings."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def build_policy_statement(*, tenant_id: int, for_update: bool = False):
        statement = select(KnowledgeSpaceFileChangePolicy).where(
            KnowledgeSpaceFileChangePolicy.tenant_id == int(tenant_id)
        )
        return statement.with_for_update() if for_update else statement

    async def get_policy(
        self,
        *,
        tenant_id: int,
        for_update: bool = False,
    ) -> KnowledgeSpaceFileChangePolicy | None:
        statement = self.build_policy_statement(tenant_id=tenant_id, for_update=for_update)
        return (await self.session.exec(statement)).first()

    async def ensure_policy_row(
        self,
        *,
        tenant_id: int,
        for_update: bool = False,
    ) -> KnowledgeSpaceFileChangePolicy:
        """Insert the tenant lock row once and recover concurrent inserts safely."""
        tenant_id = int(tenant_id)
        existing = await self.get_policy(tenant_id=tenant_id)
        if existing is not None:
            if not for_update:
                return existing
            locked = await self.get_policy(tenant_id=tenant_id, for_update=True)
            if locked is None:  # pragma: no cover - concurrent delete is forbidden by the model owner
                raise RuntimeError(f"file change policy disappeared for tenant {tenant_id}")
            return locked

        candidate = KnowledgeSpaceFileChangePolicy(tenant_id=tenant_id)
        try:
            async with self.session.begin_nested():
                self.session.add(candidate)
                await self.session.flush()
        except IntegrityError:
            # Another transaction inserted the unique tenant row. The savepoint
            # keeps the caller's UoW usable; lock the winner before quota work.
            winner = await self.get_policy(tenant_id=tenant_id, for_update=True)
            if winner is None:
                raise RuntimeError(f"concurrent file change policy insert was not visible for tenant {tenant_id}")
            return winner

        return candidate

    async def save_policy(
        self,
        *,
        tenant_id: int,
        enabled: bool,
        scope: str,
    ) -> KnowledgeSpaceFileChangePolicy:
        row = await self.ensure_policy_row(tenant_id=tenant_id, for_update=True)
        row.enabled = bool(enabled)
        row.scope = scope
        self.session.add(row)
        await self.session.flush()
        return row

    @staticmethod
    def build_setting_statement(
        *,
        tenant_id: int,
        space_id: int,
        for_update: bool = False,
    ):
        statement = select(KnowledgeSpaceFileChangeSetting).where(
            KnowledgeSpaceFileChangeSetting.tenant_id == int(tenant_id),
            KnowledgeSpaceFileChangeSetting.space_id == int(space_id),
        )
        return statement.with_for_update() if for_update else statement

    async def get_setting(
        self,
        *,
        tenant_id: int,
        space_id: int,
        for_update: bool = False,
    ) -> KnowledgeSpaceFileChangeSetting | None:
        statement = self.build_setting_statement(
            tenant_id=tenant_id,
            space_id=space_id,
            for_update=for_update,
        )
        return (await self.session.exec(statement)).first()

    async def save_setting(
        self,
        *,
        tenant_id: int,
        space_id: int,
        approval_required: bool,
    ) -> KnowledgeSpaceFileChangeSetting:
        row = await self.get_setting(
            tenant_id=tenant_id,
            space_id=space_id,
            for_update=True,
        )
        if row is None:
            row = KnowledgeSpaceFileChangeSetting(
                tenant_id=int(tenant_id),
                space_id=int(space_id),
                approval_required=bool(approval_required),
            )
        else:
            row.approval_required = bool(approval_required)
        self.session.add(row)
        await self.session.flush()
        return row

    @staticmethod
    def build_settings_by_space_ids_statement(*, tenant_id: int, space_ids: Sequence[int]):
        normalized_ids = [int(space_id) for space_id in space_ids]
        return select(KnowledgeSpaceFileChangeSetting).where(
            KnowledgeSpaceFileChangeSetting.tenant_id == int(tenant_id),
            KnowledgeSpaceFileChangeSetting.space_id.in_(normalized_ids),
        )

    async def get_settings_by_space_ids(
        self,
        *,
        tenant_id: int,
        space_ids: Sequence[int],
    ) -> list[KnowledgeSpaceFileChangeSetting]:
        if not space_ids:
            return []
        statement = self.build_settings_by_space_ids_statement(
            tenant_id=tenant_id,
            space_ids=space_ids,
        )
        return list((await self.session.exec(statement)).all())

    async def get_space(self, *, tenant_id: int, space_id: int) -> Knowledge | None:
        statement = select(Knowledge).where(
            Knowledge.tenant_id == int(tenant_id),
            Knowledge.id == int(space_id),
            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
        )
        return (await self.session.exec(statement)).first()

    async def lock_spaces_by_ids(self, *, tenant_id: int, space_ids: Sequence[int]) -> list[Knowledge]:
        """Lock a bounded current-tenant space set in deterministic order."""

        normalized_ids = sorted({int(space_id) for space_id in space_ids})
        if not normalized_ids:
            return []
        statement = (
            select(Knowledge)
            .where(
                Knowledge.tenant_id == int(tenant_id),
                Knowledge.id.in_(normalized_ids),
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            )
            .order_by(Knowledge.id.asc())
            .with_for_update()
        )
        return list((await self.session.exec(statement)).all())

    async def list_space_setting_rows(
        self,
        *,
        tenant_id: int,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[KnowledgeSpaceFileChangeSettingRow], int]:
        filters = [
            Knowledge.tenant_id == int(tenant_id),
            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
        ]
        normalized_keyword = (keyword or "").strip()
        if normalized_keyword:
            filters.append(col(Knowledge.name).contains(normalized_keyword))

        total_statement = select(func.count(Knowledge.id)).where(*filters)
        total = int((await self.session.exec(total_statement)).one())

        statement = (
            select(
                Knowledge,
                KnowledgeSpaceFileChangeSetting,
                DepartmentKnowledgeSpace.id,
            )
            .outerjoin(
                KnowledgeSpaceFileChangeSetting,
                and_(
                    KnowledgeSpaceFileChangeSetting.tenant_id == int(tenant_id),
                    KnowledgeSpaceFileChangeSetting.space_id == Knowledge.id,
                ),
            )
            .outerjoin(
                DepartmentKnowledgeSpace,
                and_(
                    DepartmentKnowledgeSpace.tenant_id == int(tenant_id),
                    DepartmentKnowledgeSpace.space_id == Knowledge.id,
                ),
            )
            .where(*filters)
            .order_by(Knowledge.id.asc())
            .offset((int(page) - 1) * int(page_size))
            .limit(int(page_size))
        )
        result = (await self.session.exec(statement)).all()
        return (
            [
                KnowledgeSpaceFileChangeSettingRow(
                    space=space,
                    setting=setting,
                    is_department=department_binding_id is not None,
                )
                for space, setting, department_binding_id in result
            ],
            total,
        )

    async def get_space_setting_row(
        self,
        *,
        tenant_id: int,
        space_id: int,
    ) -> KnowledgeSpaceFileChangeSettingRow | None:
        statement = (
            select(
                Knowledge,
                KnowledgeSpaceFileChangeSetting,
                DepartmentKnowledgeSpace.id,
            )
            .outerjoin(
                KnowledgeSpaceFileChangeSetting,
                and_(
                    KnowledgeSpaceFileChangeSetting.tenant_id == int(tenant_id),
                    KnowledgeSpaceFileChangeSetting.space_id == Knowledge.id,
                ),
            )
            .outerjoin(
                DepartmentKnowledgeSpace,
                and_(
                    DepartmentKnowledgeSpace.tenant_id == int(tenant_id),
                    DepartmentKnowledgeSpace.space_id == Knowledge.id,
                ),
            )
            .where(
                Knowledge.tenant_id == int(tenant_id),
                Knowledge.id == int(space_id),
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            )
        )
        result = (await self.session.exec(statement)).first()
        if result is None:
            return None
        space, setting, department_binding_id = result
        return KnowledgeSpaceFileChangeSettingRow(
            space=space,
            setting=setting,
            is_department=department_binding_id is not None,
        )
