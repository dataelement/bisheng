"""组织读取及文档归属写入, 写入只flush, 由调用方提交。"""

from sqlalchemy import case, or_
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.group import Group
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_organization_repository import (
    KnowledgeFileOrganizationRepository,
)


class KnowledgeFileOrganizationRepositoryImpl(
    BaseRepositoryImpl[KnowledgeFile, int], KnowledgeFileOrganizationRepository
):
    def __init__(self, session: Session | AsyncSession):
        super().__init__(session, KnowledgeFile)

    @staticmethod
    def _primary_query(user_id: int):
        return (
            select(
                UserDepartment.department_id,
                Department.id,
                Department.tenant_id,
                Department.status,
                Department.is_deleted,
            )
            .outerjoin(Department, Department.id == UserDepartment.department_id)
            .where(UserDepartment.user_id == user_id, UserDepartment.is_primary == 1)
        )

    @staticmethod
    def _unique_primary(rows, tenant_id: int) -> int | None:
        if len(rows) != 1:
            return None
        _, department_id, department_tenant_id, status, is_deleted = rows[0]
        if department_id is None or department_tenant_id != tenant_id or status != "active" or is_deleted:
            return None
        return int(department_id)

    async def primary_organization(self, user_id: int, tenant_id: int) -> int | None:
        rows = (await self.session.exec(self._primary_query(user_id))).all()
        return self._unique_primary(rows, tenant_id)

    def primary_organization_sync(self, user_id: int, tenant_id: int) -> int | None:
        return self._unique_primary(self.session.exec(self._primary_query(user_id)).all(), tenant_id)

    async def publish_organization_context(self, source_id: int, target_id: int) -> tuple:
        rows = (
            await self.session.exec(
                select(
                    KnowledgeSpaceScope.space_id,
                    KnowledgeSpaceScope.tenant_id,
                    KnowledgeSpaceScope.level,
                    KnowledgeSpaceScope.owner_type,
                    KnowledgeSpaceScope.owner_id,
                    KnowledgeSpaceScope.created_by,
                ).where(KnowledgeSpaceScope.space_id.in_([source_id, target_id]))
            )
        ).all()
        scopes = {row.space_id: row for row in rows}
        source, target = scopes.get(source_id), scopes.get(target_id)
        department = group = None
        if source is None or source.level != "personal":
            return source, target, department, group
        if target is not None:
            if target.owner_type in {"department", "user"}:
                bindings = (
                    await self.session.exec(
                        select(DepartmentKnowledgeSpace.department_id, DepartmentKnowledgeSpace.tenant_id).where(
                            DepartmentKnowledgeSpace.space_id == target_id
                        )
                    )
                ).all()
                if (
                    len(bindings) == 1
                    and (target.owner_type == "user" or bindings[0].department_id == target.owner_id)
                    and bindings[0].tenant_id == target.tenant_id
                ):
                    department = (
                        await self.session.exec(
                            select(Department.id, Department.tenant_id, Department.status, Department.is_deleted).where(
                                Department.id == bindings[0].department_id
                            )
                        )
                    ).first()
                elif not bindings and target.level == "team" and target.owner_type == "user":
                    group = (
                        await self.session.exec(
                            select(
                                Knowledge.tenant_id,
                                case(
                                    (KnowledgeSpaceScope.created_by > 0, KnowledgeSpaceScope.created_by),
                                    else_=Knowledge.user_id,
                                ).label("create_user"),
                            )
                            .join(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
                            .where(Knowledge.id == target_id)
                        )
                    ).first()
            elif target.owner_type == "user_group":
                group = (
                    await self.session.exec(
                        select(Group.id, Group.tenant_id, Group.create_user).where(Group.id == target.owner_id)
                    )
                ).first()
        return source, target, department, group

    async def set_document_organization(self, document_id: int, tenant_id: int, organization_id: int | None) -> None:
        physical_ids = select(KnowledgeDocumentVersion.knowledge_file_id).where(
            KnowledgeDocumentVersion.document_id == document_id
        )
        rows = (
            await self.session.exec(
                select(KnowledgeFile)
                .where(
                    or_(KnowledgeFile.id.in_(physical_ids), KnowledgeFile.reference_document_id == document_id),
                    KnowledgeFile.file_type == 1,
                    or_(KnowledgeFile.entry_type.is_(None), KnowledgeFile.entry_type != "projection_tombstone"),
                )
                .order_by(KnowledgeFile.id)
                .with_for_update()
            )
        ).all()
        for row in rows:
            if row.tenant_id != tenant_id:
                raise ValueError("document organization tenant mismatch")
            row.belonging_organization_id = organization_id
            self.session.add(row)
        await self.session.flush()
