"""Native knowledge facts used by legacy transport adapters."""

from sqlmodel import func, or_, select

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge


class KnowledgeCompatibilityRepository:
    async def aresource_types(self, resource_ids: list[int]) -> dict[int, str]:
        tenant_id = get_current_tenant_id()
        if type(tenant_id) is not int or tenant_id <= 0 or is_tenant_filter_bypassed():
            raise PermissionInvalidResourceError()
        ids = list(dict.fromkeys(value for value in resource_ids if type(value) is int and 0 < value <= 2**63 - 1))
        result = {}
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                for start in range(0, len(ids), 200):
                    rows = await session.exec(
                        select(Knowledge.id, Knowledge.type).where(
                            Knowledge.id.in_(ids[start : start + 200]),
                            Knowledge.type.in_((0, 1, 3)),
                        )
                    )
                    result.update(
                        (ident, "knowledge_space" if kind == 3 else "knowledge_library") for ident, kind in rows
                    )
        return result

    async def alist_space_candidates(
        self,
        *,
        keyword=None,
        sort_by="update_time",
        offset=0,
        after=None,
        limit=100,
        preferred_ids=(),
        has_abnormal=False,
    ):
        from sqlalchemy.orm import load_only
        from sqlmodel import case

        from bisheng.core.database.dialect_helpers import name_sort_clauses
        from bisheng.knowledge.domain.models.knowledge import KnowledgeRead
        from bisheng.knowledge.domain.repositories.knowledge_space_listing_repository import (
            KnowledgeSpaceListingRepository,
        )

        tenant_id = get_current_tenant_id()
        if type(tenant_id) is not int or tenant_id <= 0 or is_tenant_filter_bypassed():
            raise PermissionInvalidResourceError()
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("legacy candidate page is invalid")
        abnormal = KnowledgeSpaceListingRepository._abnormal_exists()
        fields = [getattr(Knowledge, key) for key in KnowledgeRead.model_fields if hasattr(Knowledge, key)]
        statement = (
            select(Knowledge, case((abnormal, 1), else_=0))
            .options(load_only(*fields))
            .where(
                Knowledge.type == 3,
            )
        )
        if keyword:
            from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

            files = (
                select(KnowledgeFile.id)
                .where(
                    KnowledgeFile.knowledge_id == Knowledge.id,
                    KnowledgeFile.tenant_id == Knowledge.tenant_id,
                    KnowledgeFile.file_name.like(f"%{keyword}%"),
                )
                .exists()
            )
            statement = statement.where(
                or_(Knowledge.name.like(f"%{keyword}%"), Knowledge.description.like(f"%{keyword}%"), files)
            )
        if has_abnormal:
            statement = statement.where(abnormal)
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                rank = case((Knowledge.id.in_(preferred_ids), 0), else_=1) if preferred_ids else None
                if rank is not None:
                    statement = statement.order_by(rank)
                if sort_by == "name":
                    dialect = session.get_bind().dialect.name
                    clauses = (
                        [
                            case((func.lower(func.substr(Knowledge.name, 1, 1)).between("a", "z"), 0), else_=1),
                            Knowledge.name.asc(),
                        ]
                        if dialect == "sqlite"
                        else name_sort_clauses(dialect)
                    )
                    statement = statement.order_by(*clauses, Knowledge.id.asc())
                else:
                    column = Knowledge.create_time if sort_by == "create_time" else Knowledge.update_time
                    if after is not None:
                        from bisheng.database.utils.keyset import build_keyset_where

                        columns = (column, Knowledge.id) if rank is None else (rank, column, Knowledge.id)
                        direction = True if rank is None else (False, True, True)
                        statement = statement.where(build_keyset_where(columns, after, descending=direction))
                    statement = statement.order_by(column.desc(), Knowledge.id.desc())
                rows = (await session.exec(statement.offset(offset if sort_by == "name" else 0).limit(limit))).all()
                return [(row, bool(marker)) for row, marker in rows]
