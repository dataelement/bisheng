from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.shougang_portal_course.domain.models.portal_course import (
    PortalCourse,
    PortalCourseCatalog,
)


class PortalCourseCatalogRepository:
    """Transaction-scoped persistence for multi-level course catalogs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_catalogs(
        self,
        *,
        tenant_id: int,
        include_deleted: bool = False,
        opened_only: bool = False,
    ) -> list[PortalCourseCatalog]:
        statement = select(PortalCourseCatalog).where(
            PortalCourseCatalog.tenant_id == tenant_id,
        )
        if not include_deleted:
            statement = statement.where(PortalCourseCatalog.deleted.is_(False))
        if opened_only:
            statement = statement.where(PortalCourseCatalog.opened.is_(True))
        statement = statement.order_by(
            PortalCourseCatalog.order_index.asc(),
            PortalCourseCatalog.create_time.asc(),
            PortalCourseCatalog.id.asc(),
        )
        return list((await self.session.exec(statement)).all())

    async def get_catalog(
        self,
        *,
        tenant_id: int,
        catalog_id: str,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> PortalCourseCatalog | None:
        statement = select(PortalCourseCatalog).where(
            PortalCourseCatalog.tenant_id == tenant_id,
            PortalCourseCatalog.id == catalog_id,
        )
        if not include_deleted:
            statement = statement.where(PortalCourseCatalog.deleted.is_(False))
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.exec(statement)).first()

    async def get_catalog_by_external_id(
        self,
        *,
        tenant_id: int,
        external_id: str,
        include_deleted: bool = False,
    ) -> PortalCourseCatalog | None:
        text = (external_id or "").strip()
        if not text:
            return None
        statement = select(PortalCourseCatalog).where(
            PortalCourseCatalog.tenant_id == tenant_id,
            PortalCourseCatalog.external_id == text,
        )
        if not include_deleted:
            statement = statement.where(PortalCourseCatalog.deleted.is_(False))
        return (await self.session.exec(statement)).first()

    async def find_by_import_id(
        self,
        *,
        tenant_id: int,
        import_id: str,
        include_deleted: bool = False,
    ) -> PortalCourseCatalog | None:
        found = await self.get_catalog_by_external_id(
            tenant_id=tenant_id,
            external_id=import_id,
            include_deleted=include_deleted,
        )
        if found is not None:
            return found
        return await self.get_catalog(
            tenant_id=tenant_id,
            catalog_id=import_id,
            include_deleted=include_deleted,
        )

    async def find_sibling_by_name(
        self,
        *,
        tenant_id: int,
        parent_id: str | None,
        name: str,
        exclude_id: str | None = None,
    ) -> PortalCourseCatalog | None:
        statement = select(PortalCourseCatalog).where(
            PortalCourseCatalog.tenant_id == tenant_id,
            PortalCourseCatalog.name == name,
            PortalCourseCatalog.deleted.is_(False),
        )
        if parent_id is None:
            statement = statement.where(PortalCourseCatalog.parent_id.is_(None))
        else:
            statement = statement.where(PortalCourseCatalog.parent_id == parent_id)
        if exclude_id:
            statement = statement.where(PortalCourseCatalog.id != exclude_id)
        return (await self.session.exec(statement)).first()

    async def list_children(
        self,
        *,
        tenant_id: int,
        parent_id: str | None,
        include_deleted: bool = False,
    ) -> list[PortalCourseCatalog]:
        statement = select(PortalCourseCatalog).where(
            PortalCourseCatalog.tenant_id == tenant_id,
        )
        if parent_id is None:
            statement = statement.where(PortalCourseCatalog.parent_id.is_(None))
        else:
            statement = statement.where(PortalCourseCatalog.parent_id == parent_id)
        if not include_deleted:
            statement = statement.where(PortalCourseCatalog.deleted.is_(False))
        statement = statement.order_by(
            PortalCourseCatalog.order_index.asc(),
            PortalCourseCatalog.create_time.asc(),
            PortalCourseCatalog.id.asc(),
        )
        return list((await self.session.exec(statement)).all())

    async def list_descendants(
        self,
        *,
        tenant_id: int,
        catalog: PortalCourseCatalog,
        include_deleted: bool = False,
    ) -> list[PortalCourseCatalog]:
        prefix = f"{catalog.catalog_id_path},"
        statement = select(PortalCourseCatalog).where(
            PortalCourseCatalog.tenant_id == tenant_id,
            PortalCourseCatalog.catalog_id_path.startswith(prefix),
        )
        if not include_deleted:
            statement = statement.where(PortalCourseCatalog.deleted.is_(False))
        statement = statement.order_by(PortalCourseCatalog.catalog_id_path.asc())
        return list((await self.session.exec(statement)).all())

    async def count_children(
        self,
        *,
        tenant_id: int,
        parent_id: str,
        include_deleted: bool = False,
    ) -> int:
        children = await self.list_children(
            tenant_id=tenant_id,
            parent_id=parent_id,
            include_deleted=include_deleted,
        )
        return len(children)

    async def count_courses(self, *, tenant_id: int, catalog_id: str) -> int:
        statement = select(PortalCourse.id).where(
            PortalCourse.tenant_id == tenant_id,
            PortalCourse.catalog_id == catalog_id,
        )
        return len(list((await self.session.exec(statement)).all()))

    async def count_courses_by_ids(
        self,
        *,
        tenant_id: int,
        catalog_ids: list[str],
        enabled_only: bool = False,
    ) -> dict[str, int]:
        if not catalog_ids:
            return {}
        counts: dict[str, int] = dict.fromkeys(catalog_ids, 0)
        statement = select(PortalCourse).where(
            PortalCourse.tenant_id == tenant_id,
            PortalCourse.catalog_id.in_(catalog_ids),
        )
        if enabled_only:
            statement = statement.where(PortalCourse.enabled.is_(True))
        for course in (await self.session.exec(statement)).all():
            if course.catalog_id:
                counts[course.catalog_id] = counts.get(course.catalog_id, 0) + 1
        return counts

    async def add(self, model: PortalCourseCatalog) -> None:
        self.session.add(model)
        await self.session.flush()
