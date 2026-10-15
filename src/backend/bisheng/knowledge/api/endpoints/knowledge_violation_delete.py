"""知识文档违规删除接口."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.domain.services.knowledge_violation_delete_service import (
    KnowledgeViolationDeleteService,
    ViolationCommit,
    ViolationPreview,
)

router = APIRouter(prefix="/knowledge/space", tags=["knowledge_violation_delete"])


class ViolationDeleteBody(BaseModel):
    """确认违规删除. rule_code 为空表示只删除不扣分."""

    rule_code: str | None = Field(default=None, max_length=32)
    remark: str | None = Field(default=None, max_length=200)


def _preview_data(preview: ViolationPreview) -> dict:
    """把预览转成接口数据.

    Args:
        preview: 服务层预览.

    Returns:
        预览 JSON.
    """
    return {
        "file_id": preview.file_id,
        "document_id": preview.document_id,
        "scope_tier": preview.scope_tier,
        "libraries": [
            {
                "space_id": item.space_id,
                "level": item.level,
                "entry_type": item.entry_type,
                "file_id": item.file_id,
            }
            for item in preview.libraries
        ],
        "payee_user_id": preview.payee_user_id,
        "can_deduct": preview.can_deduct,
        "reason": preview.reason,
        "rule_code": preview.rule_code,
        "score": preview.score,
        "rules": preview.rules,
    }


def _commit_data(result: ViolationCommit) -> dict:
    """把确认结果转成接口数据.

    Args:
        result: 服务层确认结果.

    Returns:
        确认 JSON.
    """
    return {
        "deleted": result.deleted,
        "document_id": result.document_id,
        "deducted": result.deducted,
        "pending_deduct": result.pending_deduct,
        "reason": result.reason,
        "scope_tier": result.scope_tier,
        "score": result.score,
        "rule_code": result.rule_code,
        "target_user_id": result.target_user_id,
    }


@router.post("/files/{file_id}/violation-delete/preview")
async def preview_violation_delete(
    file_id: int,
    body: ViolationDeleteBody | None = None,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """预览违规删除的影响档位和扣分, 不写库.

    Args:
        file_id: 非个人库里的文件入口.
        body: 可选规则编码. 空则返回当前档下各启用规则的分值.
        login_user: 当前登录用户.

    Returns:
        将删除的入口, 档位, 以及是否会扣分.
    """
    payload = body or ViolationDeleteBody()
    preview = await KnowledgeViolationDeleteService().preview(
        operator=login_user,
        file_id=file_id,
        rule_code=payload.rule_code,
    )
    return resp_200(_preview_data(preview))


@router.post("/files/{file_id}/violation-delete")
async def commit_violation_delete(
    file_id: int,
    body: ViolationDeleteBody | None = None,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """违规删除同一份文档的原件和全部发布, 分享副本.

    Args:
        file_id: 非个人库里的文件入口.
        body: 规则编码为空则只删除不扣分.
        login_user: 当前登录用户.

    Returns:
        删除结果和扣分结果.
    """
    payload = body or ViolationDeleteBody()
    result = await KnowledgeViolationDeleteService().commit(
        operator=login_user,
        file_id=file_id,
        rule_code=payload.rule_code,
        remark=payload.remark,
    )
    return resp_200(_commit_data(result))
