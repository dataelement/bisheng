from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, UniqueConstraint, text, update
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class DepartmentKnowledgeSpaceBase(SQLModelSerializable):
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    department_id: int = Field(
        sa_column=Column(
            ForeignKey("department.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        description="Department.id",
    )
    space_id: int = Field(
        sa_column=Column(
            ForeignKey("knowledge.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        description="Knowledge Space id",
    )
    created_by: int = Field(default=0, index=True, description="Creator user id (audit only, never surfaced)")
    admin_user_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=True,
            index=True,
            comment="F045: the single space admin; NULL means the space is pending admin configuration",
        ),
        description="The single space admin user id; NULL = pending admin configuration",
    )
    approval_enabled: bool = Field(
        default=True,
        description="Whether uploads in this department knowledge space require approval",
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("1"),
        ),
    )
    sensitive_check_enabled: bool = Field(
        default=False,
        description="Whether uploads in this department knowledge space require content safety check",
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("0"),
        ),
    )
    is_hidden: bool = Field(
        default=False,
        description="Hidden from the department knowledge space management list; "
        "the knowledge space, files and member permissions are all preserved",
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("0"),
        ),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )


class DepartmentKnowledgeSpace(DepartmentKnowledgeSpaceBase, table=True):
    __tablename__ = "department_knowledge_space"
    __table_args__ = (
        UniqueConstraint("department_id", name="uk_dks_department_id"),
        UniqueConstraint("space_id", name="uk_dks_space_id"),
    )

    id: int | None = Field(default=None, primary_key=True)


class DepartmentKnowledgeSpaceDao(DepartmentKnowledgeSpaceBase):
    @classmethod
    async def aget_all(cls) -> list[DepartmentKnowledgeSpace]:
        async with get_async_db_session() as session:
            result = await session.exec(select(DepartmentKnowledgeSpace))
            return result.all()

    @classmethod
    async def acreate(
        cls,
        *,
        tenant_id: int,
        department_id: int,
        space_id: int,
        created_by: int,
        admin_user_id: int | None = None,
        approval_enabled: bool = True,
        sensitive_check_enabled: bool = False,
    ) -> DepartmentKnowledgeSpace:
        row = DepartmentKnowledgeSpace(
            tenant_id=tenant_id,
            department_id=department_id,
            space_id=space_id,
            created_by=created_by,
            admin_user_id=admin_user_id,
            approval_enabled=approval_enabled,
            sensitive_check_enabled=sensitive_check_enabled,
        )
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    @classmethod
    async def aupdate(cls, row: DepartmentKnowledgeSpace) -> DepartmentKnowledgeSpace:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    @classmethod
    async def aset_hidden_by_department_ids(
        cls,
        department_ids: list[int],
        is_hidden: bool,
    ) -> int:
        """Bulk hide/restore department knowledge spaces by department id.

        Goes through a SELECT first so the multi-tenant SELECT filter scopes the
        rows (a raw bulk UPDATE bypasses the tenant listener). Returns the number
        of rows whose state actually changed.
        """
        if not department_ids:
            return 0
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentKnowledgeSpace).where(
                    DepartmentKnowledgeSpace.department_id.in_(department_ids),
                )
            )
            rows = result.all()
            changed = 0
            for row in rows:
                if row.is_hidden != is_hidden:
                    row.is_hidden = is_hidden
                    session.add(row)
                    changed += 1
            if changed:
                await session.commit()
            return changed

    @classmethod
    async def aget_by_admin_user_id(
        cls,
        admin_user_id: int,
    ) -> list[DepartmentKnowledgeSpace]:
        """All department spaces currently administered by ``admin_user_id``."""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentKnowledgeSpace).where(
                    DepartmentKnowledgeSpace.admin_user_id == admin_user_id,
                )
            )
            return result.all()

    @classmethod
    async def areplace_admin(
        cls,
        *,
        row_id: int,
        expected_admin_user_id: int | None,
        new_admin_user_id: int | None,
    ) -> bool:
        """Atomically swap the space admin, guarded by the expected current value.

        Uses a conditional single-row UPDATE so two concurrent replacements can
        never interleave into a lost update: the second writer sees a stale
        ``expected_admin_user_id`` and gets ``False``. The row is re-read via a
        tenant-filtered SELECT first, so the bulk-UPDATE tenant-injection gap
        (backend AGENTS.md pitfall) does not apply — the WHERE is on the PK.
        """
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentKnowledgeSpace).where(
                    DepartmentKnowledgeSpace.id == row_id,
                )
            )
            row = result.first()
            if row is None or row.admin_user_id != expected_admin_user_id:
                return False
            stmt = (
                update(DepartmentKnowledgeSpace)
                .where(
                    DepartmentKnowledgeSpace.id == row_id,
                    (
                        DepartmentKnowledgeSpace.admin_user_id.is_(None)
                        if expected_admin_user_id is None
                        else DepartmentKnowledgeSpace.admin_user_id == expected_admin_user_id
                    ),
                )
                .values(admin_user_id=new_admin_user_id)
            )
            exec_result = await session.exec(stmt)
            await session.commit()
            return exec_result.rowcount == 1

    @classmethod
    async def aget_by_department_id(
        cls,
        department_id: int,
    ) -> DepartmentKnowledgeSpace | None:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentKnowledgeSpace).where(
                    DepartmentKnowledgeSpace.department_id == department_id,
                )
            )
            return result.first()

    @classmethod
    async def aget_by_department_ids(
        cls,
        department_ids: list[int],
    ) -> list[DepartmentKnowledgeSpace]:
        if not department_ids:
            return []
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentKnowledgeSpace).where(
                    DepartmentKnowledgeSpace.department_id.in_(department_ids),
                )
            )
            return result.all()

    @classmethod
    async def aget_by_space_id(
        cls,
        space_id: int,
    ) -> DepartmentKnowledgeSpace | None:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentKnowledgeSpace).where(
                    DepartmentKnowledgeSpace.space_id == space_id,
                )
            )
            return result.first()

    @classmethod
    async def aget_by_space_ids(
        cls,
        space_ids: list[int],
    ) -> list[DepartmentKnowledgeSpace]:
        if not space_ids:
            return []
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentKnowledgeSpace).where(
                    DepartmentKnowledgeSpace.space_id.in_(space_ids),
                )
            )
            return result.all()

    @classmethod
    async def aget_space_id_by_department_id(
        cls,
        department_id: int,
    ) -> int | None:
        row = await cls.aget_by_department_id(department_id)
        return row.space_id if row else None

    @classmethod
    async def aget_department_ids_by_space_ids(
        cls,
        space_ids: list[int],
    ) -> dict[int, int]:
        rows = await cls.aget_by_space_ids(space_ids)
        return {row.space_id: row.department_id for row in rows}
