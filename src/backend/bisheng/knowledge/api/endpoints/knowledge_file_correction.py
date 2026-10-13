"""知识库文档纠错接口."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.domain.services.knowledge_file_correction_service import (
    KnowledgeFileCorrectionService,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge_file_correction"])


class SubmitFileCorrectionBody(BaseModel):
    """提交纠错的请求体. 字数由服务端按字符校验."""

    content: str = ""


class RegisterCorrectionUpdateFileBody(BaseModel):
    """采纳并更新时, 已经上传到临时目录的文件路径."""

    file_path: str = Field(min_length=1)


@router.get("/files/{file_id}/corrections")
async def list_file_corrections(
    file_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """列出这篇文档的纠错和状态.

    Args:
        file_id: 知识库文件 ID.
        login_user: 当前登录用户.

    Returns:
        纠错摘要, 含反馈人, 说明和状态.
    """
    data = await KnowledgeFileCorrectionService.list_for_file(
        login_user=login_user,
        file_id=file_id,
    )
    return resp_200(data)


@router.post("/files/{file_id}/corrections")
async def submit_file_correction(
    file_id: int,
    body: SubmitFileCorrectionBody,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """提交文档纠错.

    Args:
        file_id: 知识库文件 ID.
        body: 纠错说明.
        login_user: 当前登录用户.

    Returns:
        纠错单编号和待处理状态.
    """
    data = await KnowledgeFileCorrectionService.submit(
        login_user=login_user,
        file_id=file_id,
        content=body.content,
    )
    return resp_200(data)


@router.post("/file-corrections/{correction_id}/update-file")
async def register_correction_update_file(
    correction_id: int,
    body: RegisterCorrectionUpdateFileBody,
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """登记采纳并更新的新文件, 不记入库分.

    Args:
        correction_id: 待处理纠错单 ID.
        body: 临时文件路径.
        request: 当前请求.
        login_user: 当前登录用户, 必须是冻结上传人.

    Returns:
        新文件 id 和解析状态.
    """
    data = await KnowledgeFileCorrectionService.register_update_file(
        login_user=login_user,
        request=request,
        correction_id=correction_id,
        file_path=body.file_path,
    )
    return resp_200(data)


@router.get("/file-corrections/{correction_id}")
async def get_file_correction(
    correction_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """读取纠错说明.

    Args:
        correction_id: 纠错单 ID.
        login_user: 当前登录用户.

    Returns:
        纠错说明. 非当事人得到 18407.
    """
    data = await KnowledgeFileCorrectionService.get_content(
        login_user=login_user,
        correction_id=correction_id,
    )
    return resp_200(data)
