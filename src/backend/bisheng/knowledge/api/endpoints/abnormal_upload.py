"""当前租户异常上传: 平台管理员和超管查看、重新解析、普通删除."""

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200, resp_500
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.abnormal_upload_service import AbnormalUploadService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

router = APIRouter(prefix="/knowledge/space", tags=["knowledge_abnormal_upload"])


class AbnormalUploadBatchDeleteBody(BaseModel):
    file_ids: list[int] = Field(default_factory=list)


def _service(
    request: Request,
    session: AsyncSession,
    login_user: UserPayload,
) -> AbnormalUploadService:
    return AbnormalUploadService(
        login_user=login_user,
        file_repository=KnowledgeFileRepositoryImpl(session),
        space_service=KnowledgeSpaceService(request=request, login_user=login_user),
    )


def _list_error_message(exc: ValueError) -> str:
    if "page" in str(exc):
        return "分页参数不正确"
    return "筛选参数不正确"


@router.get("/abnormal-uploads")
async def list_abnormal_uploads(
    request: Request,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    status: int | None = Query(default=None),
    space_level: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    knowledge_name: str | None = Query(default=None),
    uploader_name: str | None = Query(default=None),
    uploader_company: str | None = Query(default=None),
    uploader_department: str | None = Query(default=None),
    uploader_office: str | None = Query(default=None),
    update_time_from: str | None = Query(default=None),
    update_time_to: str | None = Query(default=None),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = _service(request, session, login_user)
    try:
        data = await service.list_uploads(
            page=page,
            page_size=page_size,
            status=status,
            space_level=space_level,
            keyword=keyword,
            knowledge_name=knowledge_name,
            uploader_name=uploader_name,
            uploader_company=uploader_company,
            uploader_department=uploader_department,
            uploader_office=uploader_office,
            update_time_from=update_time_from,
            update_time_to=update_time_to,
        )
    except ValueError as exc:
        return resp_500(code=422, message=_list_error_message(exc))
    return resp_200(data)


@router.get("/abnormal-uploads/org-options")
async def list_abnormal_upload_org_options(
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = _service(request, session, login_user)
    return resp_200(await service.list_org_options())


@router.post("/abnormal-uploads/retry-batch")
async def retry_abnormal_uploads_batch(
    body: AbnormalUploadBatchDeleteBody,
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = _service(request, session, login_user)
    try:
        data = await service.retry_batch(body.file_ids)
    except ValueError:
        return resp_500(code=422, message="批量解析参数不正确")
    if data["failed"]:
        message = f"已开始重新解析 {data['retried']} 条，{data['failed']} 条未解析"  # noqa: RUF001
    else:
        message = f"已开始重新解析 {data['retried']} 条"
    return resp_200(data, message=message)


@router.post("/abnormal-uploads/delete-batch")
async def delete_abnormal_uploads_batch(
    body: AbnormalUploadBatchDeleteBody,
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = _service(request, session, login_user)
    try:
        data = await service.delete_batch(body.file_ids)
    except ValueError:
        return resp_500(code=422, message="批量删除参数不正确")
    if data["failed"]:
        message = f"已删除 {data['deleted']} 条，{data['failed']} 条未删除"  # noqa: RUF001
    else:
        message = f"已删除 {data['deleted']} 条"
    return resp_200(data, message=message)


@router.post("/abnormal-uploads/{file_id}/retry")
async def retry_abnormal_upload(
    file_id: int,
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = _service(request, session, login_user)
    await service.retry(file_id)
    return resp_200({"file_id": file_id}, message="已开始重新解析")


@router.post("/abnormal-uploads/{file_id}/delete")
async def delete_abnormal_upload(
    file_id: int,
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = _service(request, session, login_user)
    await service.delete(file_id)
    return resp_200({"file_id": file_id}, message="已删除")
