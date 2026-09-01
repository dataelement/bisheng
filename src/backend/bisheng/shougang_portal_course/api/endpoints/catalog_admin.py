from __future__ import annotations

from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.portal_course import PortalCourseCatalogImportError
from bisheng.common.schemas.api import resp_200
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.shougang_portal_course.domain.schemas.portal_course_schema import (
    CatalogCreate,
    CatalogUpdate,
    OrderUpdate,
)
from bisheng.shougang_portal_course.domain.services.catalog_service import (
    PortalCourseCatalogService,
)

router = APIRouter(
    prefix="/shougang-portal/course-admin",
    tags=["shougang-portal-course-admin"],
)


def _tenant_id(user: UserPayload) -> int:
    return int(get_current_tenant_id() or user.tenant_id)


def _dump(item) -> dict:
    return item.model_dump(mode="json", exclude_none=True)


@router.get("/catalogs")
async def list_catalogs(
    include_deleted: bool = Query(default=False),
    as_tree: bool = Query(default=True),
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    async with get_async_db_session() as session:
        items = await PortalCourseCatalogService(session).list_read_models(
            tenant_id=_tenant_id(admin_user),
            public_only=False,
            include_deleted=include_deleted,
            as_tree=as_tree,
        )
    return resp_200({"items": [_dump(item) for item in items]})


@router.post("/catalogs")
async def create_catalog(
    payload: CatalogCreate,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    tenant_id = _tenant_id(admin_user)
    async with get_async_db_session() as session:
        async with session.begin():
            catalog = await PortalCourseCatalogService(session).create_catalog(
                tenant_id=tenant_id,
                user_id=admin_user.user_id,
                payload=payload,
            )
            catalog_id = catalog.id
        item = await PortalCourseCatalogService(session).get_read_model(
            tenant_id=tenant_id,
            catalog_id=catalog_id,
        )
    return resp_200(_dump(item))


async def _read_excel_upload(file: UploadFile) -> bytes:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise PortalCourseCatalogImportError(msg="请上传 xlsx 或 xls 文件")
    content = await file.read()
    if not content:
        raise PortalCourseCatalogImportError(msg="导入文件为空")
    return content


@router.get("/catalogs/template")
async def download_catalog_template(
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    async with get_async_db_session() as session:
        data = PortalCourseCatalogService(session).build_template()
    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                'attachment; filename="course-catalog-import-template.xlsx"; '
                f"filename*=UTF-8''{quote('课程目录导入模板.xlsx', safe='')}"
            )
        },
    )


@router.post("/catalogs/import/preview")
async def preview_catalog_import(
    file: UploadFile = File(...),
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    content = await _read_excel_upload(file)
    async with get_async_db_session() as session:
        result = await PortalCourseCatalogService(session).preview_excel(
            tenant_id=_tenant_id(admin_user),
            content=content,
        )
    return resp_200(result.model_dump())


@router.post("/catalogs/import")
async def import_catalogs(
    file: UploadFile = File(...),
    force: bool = Query(default=False),
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    content = await _read_excel_upload(file)
    async with get_async_db_session() as session:
        async with session.begin():
            result = await PortalCourseCatalogService(session).import_excel(
                tenant_id=_tenant_id(admin_user),
                user_id=admin_user.user_id,
                content=content,
                force=force,
            )
    return resp_200(result.model_dump())


@router.put("/catalogs/order")
async def update_catalog_order(
    payload: OrderUpdate,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    async with get_async_db_session() as session:
        async with session.begin():
            await PortalCourseCatalogService(session).update_catalog_order(
                tenant_id=_tenant_id(admin_user),
                payload=payload,
            )
    return resp_200({"updated": True})


@router.get("/catalogs/{catalog_id}")
async def get_catalog(
    catalog_id: str,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    async with get_async_db_session() as session:
        item = await PortalCourseCatalogService(session).get_read_model(
            tenant_id=_tenant_id(admin_user),
            catalog_id=catalog_id,
        )
    return resp_200(_dump(item))


@router.put("/catalogs/{catalog_id}")
async def update_catalog(
    catalog_id: str,
    payload: CatalogUpdate,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    tenant_id = _tenant_id(admin_user)
    async with get_async_db_session() as session:
        async with session.begin():
            await PortalCourseCatalogService(session).update_catalog(
                tenant_id=tenant_id,
                user_id=admin_user.user_id,
                catalog_id=catalog_id,
                payload=payload,
            )
        item = await PortalCourseCatalogService(session).get_read_model(
            tenant_id=tenant_id,
            catalog_id=catalog_id,
        )
    return resp_200(_dump(item))


@router.delete("/catalogs/{catalog_id}")
async def delete_catalog(
    catalog_id: str,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    async with get_async_db_session() as session:
        async with session.begin():
            await PortalCourseCatalogService(session).delete_catalog(
                tenant_id=_tenant_id(admin_user),
                catalog_id=catalog_id,
            )
    return resp_200({"deleted": True})
