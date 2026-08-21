# ruff: noqa: RUF002, RUF003
"""
Expert QA API Endpoints - HTTP 路由处理层
"""

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile, status
from fastapi.responses import Response
from loguru import logger

from bisheng.api.v1.schemas import UploadFileResponse
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.http_error import ServerError
from bisheng.common.schemas.api import resp_200, resp_500
from bisheng.common.utils.beijing_time import dump_qa_datetimes
from bisheng.core.cache.utils import save_uploaded_file
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.qa_expert.domain.asset_service import infer_qa_content_type
from bisheng.qa_expert.domain.moderate_delete_service import ModerateDeleteService
from bisheng.qa_expert.domain.rich_text import question_description_to_plain_text
from bisheng.qa_expert.domain.schemas import (
    AdoptAnswerRequest,
    AnswerCreateRequest,
    AnswerDetailResponse,
    AnswerUpdateRequest,
    CommentCreateRequest,
    CommentDetailResponse,
    CommentPageData,
    ExpertCreateRequest,
    ExpertResponse,
    ExpertUpdateRequest,
    GetCommentsRequest,
    ModerateDeleteRequest,
    PublishCreateRequest,
    QAExpertStatsResponse,
    QANotificationResponse,
    QuestionCheckRequest,
    QuestionCreateRequest,
    QuestionDetailResponse,
    QuestionListQuery,
    QuestionPageData,
    QuestionUpdateRequest,
    VoteRequest,
)
from bisheng.qa_expert.domain.services import (
    AnswerService,
    CommentService,
    ExpertService,
    QAExpertStatsService,
    QuestionService,
    VoteService,
)
from bisheng.sensitive_word.domain.schemas import SensitiveWordBusinessType
from bisheng.sensitive_word.domain.services.exceptions import ContentSafetyViolation
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import (
    SensitiveWordPolicyService,
)

router = APIRouter(prefix="/qa_experts", tags=["Expert QA"])

# ==================== 统计 Endpoints ====================


async def get_stats_service() -> QAExpertStatsService:
    """Dependency injection: Expert QA statistics service."""
    return QAExpertStatsService()


@router.get("/stats", response_model=QAExpertStatsResponse)
async def get_qa_expert_stats(
    _user: UserPayload = Depends(UserPayload.get_login_user),
    service: QAExpertStatsService = Depends(get_stats_service),
):
    """Get Expert QA overview statistics."""
    stats = await service.get_overview_stats()
    return resp_200(data=stats)


# ==================== 专家管理 Endpoints ====================


async def get_expert_service() -> ExpertService:
    """依赖注入：专家服务"""
    return ExpertService()


@router.get("/experts", response_model=list[ExpertResponse])
async def list_experts(
    keyword: str | None = Query(None, description="搜索关键词"),
    department_id: str | None = Query(None, description="部门 ID"),
    job_family: str | None = Query(None, description="职位族"),
    job_category: str | None = Query(None, description="职位类"),
    position: str | None = Query(None, description="职务"),
    major: str | None = Query(None, description="岗位"),
    sort_by: Literal[
        "expert_name",
        "department",
        "job_family",
        "job_category",
        "position",
        "major",
        "expert_score",
        "created_at",
    ] = Query("created_at", description="排序字段"),
    sort_order: Literal["asc", "desc"] = Query("desc", description="排序方向"),
    answer_desc: bool | None = Query(None, description="回答数排序"),
    adoption_desc: bool | None = Query(None, description="采纳数排序"),
    vote_desc: bool | None = Query(None, description="点赞数排序"),
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=500, description="每页数量"),
    service: ExpertService = Depends(get_expert_service),
):
    """列表查询专家"""
    skip = (page - 1) * limit
    experts, total = await service.list_experts(
        keyword=keyword,
        department_id=department_id,
        job_family=job_family,
        job_category=job_category,
        position=position,
        major=major,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
        answer_desc=answer_desc,
        adoption_desc=adoption_desc,
        vote_desc=vote_desc,
    )
    return resp_200(data={"experts": experts, "total": total})


@router.get("/experts/filter-options")
async def list_expert_filter_options(
    service: ExpertService = Depends(get_expert_service),
):
    """获取部门、职位族、职位类、职务和岗位筛选项。"""
    return resp_200(data=await service.list_filter_options())


# ==================== 专家管理 Endpoints (补全) ====================


@router.post("/experts", response_model=ExpertResponse)
async def create_expert(
    request: ExpertCreateRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: ExpertService = Depends(get_expert_service),
):
    """创建专家（专家库管理员）"""
    try:
        expert = await service.create_expert(request, user=user)
        return resp_200(data=_jsonable(expert))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()
    except Exception as e:
        return resp_500(code=500, message=str(e))


@router.put("/experts/{expert_id}", response_model=ExpertResponse)
async def update_expert(
    expert_id: int,
    request: ExpertUpdateRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: ExpertService = Depends(get_expert_service),
):
    """更新专家信息"""
    try:
        expert = await service.update_expert(expert_id, request, user=user)
        return resp_200(data=_jsonable(expert))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()
    except Exception as e:
        return resp_500(code=500, message=str(e))


@router.delete("/experts/{expert_id}", deprecated=True)
async def delete_expert(
    expert_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: ExpertService = Depends(get_expert_service),
):
    """删除专家（兼容：映射为停用）"""
    try:
        success = await service.delete_expert(expert_id, user=user)
        if not success:
            return resp_500(code=500, message="Failed to disable expert")
        return resp_200(data={"message": "Expert disabled successfully", "deprecated": True})
    except BaseErrorCode as exc:
        return exc.return_resp_instance()
    except Exception as e:
        return resp_500(code=500, message=str(e))


@router.post("/experts/{expert_id}/disable")
async def disable_expert(
    expert_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: ExpertService = Depends(get_expert_service),
):
    """停用专家"""
    try:
        expert = await service.disable_expert(expert_id, user)
        return resp_200(data=_jsonable(expert))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()
    except Exception as e:
        return resp_500(code=500, message=str(e))


@router.post("/experts/{expert_id}/enable")
async def enable_expert(
    expert_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: ExpertService = Depends(get_expert_service),
):
    """恢复专家"""
    try:
        expert = await service.enable_expert(expert_id, user)
        return resp_200(data=_jsonable(expert))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()
    except Exception as e:
        return resp_500(code=500, message=str(e))


@router.get("/experts/name/{expert_name}")
async def expertsinfo(
    expert_name: str,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: ExpertService = Depends(get_expert_service),
):
    """获取专家"""

    experinfo = await service.get_expertinfo(expert_name)
    return resp_200(data=dump_qa_datetimes(experinfo))


@router.get("/experts/userid/{user_id}")
async def expertsinfo_id(
    user_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: ExpertService = Depends(get_expert_service),
):
    """获取专家"""

    experinfo = await service.get_expertinfobyid(user_id)
    return resp_200(data=dump_qa_datetimes(experinfo))


# ==================== 问题管理 Endpoints ====================


async def get_question_service() -> QuestionService:
    """依赖注入：问题服务"""
    return QuestionService()


def check_question_content(tenant_id: int, text: str) -> None:
    result = SensitiveWordPolicyService.check_text(
        tenant_id=tenant_id,
        business_type=SensitiveWordBusinessType.KNOWLEDGE_SPACE_FILE_PARSE,
        text=text,
    )
    if result.enabled and result.hits:
        raise ContentSafetyViolation(result)


@router.post("/check_questions", response_model=QuestionDetailResponse)
async def check_question(
    request: QuestionCheckRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    check_question_content(user.tenant_id, request.check_text)
    return resp_200()


@router.post("/questions", response_model=QuestionDetailResponse)
async def create_question(
    request: QuestionCreateRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: QuestionService = Depends(get_question_service),
):
    """发起提问"""
    if not user.user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    check_question_content(
        user.tenant_id,
        f"{request.title}\n{question_description_to_plain_text(request.description)}",
    )
    question = await service.create_question(
        user.user_id,
        request,
        user.user_name,
        tenant_id=user.tenant_id,
    )
    return resp_200(data=question_detail_payload(question))


@router.get("/questions", response_model=QuestionPageData)
async def list_questions(
    query: QuestionListQuery = Depends(),
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: QuestionService = Depends(get_question_service),
):
    """问题列表"""

    questions, total = await service.list_questions(
        business_domain=query.domain,
        status=query.status,
        sort_by=query.sort_by,
        user_id=user.user_id,
        skip=(query.page - 1) * query.page_size,
        limit=query.page_size,
        user=user,
        list_filter=query.filter,
        display_status=query.display_status,
        keyword=query.keyword,
    )

    return resp_200(
        data={
            "questions": [question_detail_payload(item) for item in questions],
            "total": total,
        }
    )


@router.get("/questions/answer_count/domain", response_model=list[dict])
async def get_answer_count_by_domain(
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: QuestionService = Depends(get_question_service),
):
    """获取每个业务域的回答数"""
    answer_count = await service.get_answer_count_by_domain()
    return resp_200(data=answer_count)


@router.put("/questions/{question_id}", response_model=ExpertResponse)
async def update_question(
    question_id: int,
    request: QuestionUpdateRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: QuestionService = Depends(get_question_service),
):
    """更新问题信息"""
    if request.description is not None:
        check_question_content(
            user.tenant_id,
            f"{request.title or ''}\n{question_description_to_plain_text(request.description)}",
        )

    question = await service.update_question(question_id, request, tenant_id=user.tenant_id)
    return resp_200(data=question_detail_payload(question))


def question_detail_payload(question) -> dict:
    """把 ORM 上挂的响应态字段打进 JSON。

    SQLModel.model_dump() 只含表列。无关联文档时旧逻辑直接返回 ORM，
    capabilities / display_status / asker 会被丢掉，详情页就会没有回答框、采纳、转公开入口。
    """
    if isinstance(question, dict):
        payload = dict(question)
    elif hasattr(question, "model_dump"):
        payload = question.model_dump()
    else:
        payload = {}
    for key in (
        "display_status",
        "capabilities",
        "related_doc_views",
        "asker",
        "latest_answer",
        "active_publish_request",
        "latest_publish_request",
        "question_type",
        "content_locked",
    ):
        value = getattr(question, key, payload.get(key))
        if value is not None:
            payload[key] = value
    caps = payload.get("capabilities")
    if caps is not None and not isinstance(caps, dict):
        payload["capabilities"] = getattr(caps, "__dict__", caps)
    views = payload.get("related_doc_views")
    if views:
        payload["related_docs"] = views
        payload["related_doc_views"] = views
    # 匿名题不得把 created_by 真名留给前端自己藏；非管理员 JSON 改成别名。
    asker = payload.get("asker")
    if isinstance(asker, dict) and asker.get("anonymous") and "real_name" not in asker:
        payload["created_by"] = asker.get("display_name")
    return dump_qa_datetimes(payload)


def answer_payload(answer) -> dict:
    """回答 JSON：SQLModel dump 不含 author；匿名时 expert_name 改成别名，不写回表列。"""
    if isinstance(answer, dict):
        payload = dict(answer)
        author = payload.get("author")
    elif hasattr(answer, "model_dump"):
        try:
            payload = answer.model_dump()
        except TypeError:
            payload = answer.model_dump()
        author = getattr(answer, "author", payload.get("author"))
    else:
        payload = {}
        author = getattr(answer, "author", None)
    if author is not None:
        payload["author"] = author
    if isinstance(author, dict) and author.get("anonymous") and "real_name" not in author:
        payload["expert_name"] = author.get("display_name")
    expert = payload.get("expert") if isinstance(answer, dict) else getattr(answer, "expert", payload.get("expert"))
    if expert is not None:
        payload["expert"] = expert
    else:
        payload.pop("expert", None)
    can_delete = getattr(answer, "can_delete", payload.get("can_delete"))
    if can_delete is not None:
        payload["can_delete"] = bool(can_delete)
    related_doc_views = getattr(answer, "related_doc_views", payload.get("related_doc_views"))
    if related_doc_views is not None:
        payload["related_doc_views"] = related_doc_views
    return dump_qa_datetimes(payload)


def comment_payload(comment) -> dict:
    """评论 JSON：走 CommentDetailResponse，匿名时 user_name 为别名。"""
    if isinstance(comment, dict):
        return dump_qa_datetimes(dict(comment))
    return dump_qa_datetimes(CommentDetailResponse.from_comment(comment).model_dump())


@router.get("/questions/{question_id}", response_model=QuestionDetailResponse)
async def get_question_detail(
    question_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: QuestionService = Depends(get_question_service),
):
    """获取问题详情"""
    question = await service.get_question_detail(question_id, user.user_id, user=user)
    return resp_200(data=question_detail_payload(question))


@router.get("/questions/similar", response_model=QuestionPageData)
async def list_similar_questions(
    text: str = Query(default="", max_length=200),
    limit: int = Query(default=5, ge=1, le=10),
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: QuestionService = Depends(get_question_service),
):
    """类似问题：仅返回当前用户可见的题，不阻断发布。"""
    questions = await service.find_similar_questions(user=user, text=text, limit=limit)
    return resp_200(
        data={
            "questions": [question_detail_payload(item) for item in questions],
            "total": len(questions),
        }
    )


@router.post("/questions/{question_id}/adopt", response_model=QuestionDetailResponse)
async def adopt_answer(
    question_id: int,
    request: AdoptAnswerRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: QuestionService = Depends(get_question_service),
):
    """采纳最佳回答"""

    question = await service.adopt_answer(question_id, request.answer_id, user.user_id)
    return resp_200(data=question_detail_payload(question))


@router.delete("/questions/{question_id}")
async def delete_question(
    question_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: QuestionService = Depends(get_question_service),
):
    """删除回答"""
    try:
        success = await service.delete_question(
            question_id,
            tenant_id=user.tenant_id,
        )

        return resp_200(data={"success": success})
    except Exception as e:
        return resp_500(code=500, message=str(e))


# ==================== 回答管理 Endpoints ====================


async def get_answer_service() -> AnswerService:
    """依赖注入：回答服务"""
    return AnswerService()


@router.post("/answers", response_model=AnswerDetailResponse)
async def create_answer(
    request: AnswerCreateRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: AnswerService = Depends(get_answer_service),
):
    """发布回答"""
    if not user.user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    answer = await service.create_answer(user.user_id, request, tenant_id=user.tenant_id, user=user)
    if not isinstance(answer, dict):
        answer = await service.attach_author(answer, user)
    return resp_200(data=answer_payload(answer))


# 根据问题id获取回答数据
@router.get("/answers/{question_id}", response_model=list[AnswerDetailResponse])
async def get_answers(
    question_id: int = Path(..., ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    sort_by: str | None = Query(None),
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: AnswerService = Depends(get_answer_service),
):
    """获取问题的所有回答"""
    answers, total = await service.get_answers(question_id, (page - 1) * page_size, page_size, sort_by, user=user)
    return resp_200(data={"answers": [answer_payload(item) for item in answers], "total": total})


@router.get("/questions/{question_id}/answers")
async def get_answersbyname(
    question_id: int = Path(..., ge=1),
    expert_name: str | None = Query(None),
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: AnswerService = Depends(get_answer_service),
):
    """获取问题的所有回答"""
    answers = await service.get_by_expertname(expert_name, question_id, user=user)
    return resp_200(data=answer_payload(answers) if answers is not None else answers)


@router.put("/answers/{answer_id}", response_model=AnswerDetailResponse)
async def update_answer(
    answer_id: int,
    request: AnswerUpdateRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: AnswerService = Depends(get_answer_service),
):
    """更新回答"""
    try:
        answer = await service.update_answer(
            answer_id,
            user.user_id,
            content=request.content,
            attachments=request.attachments,
            related_docs=request.related_docs,
            images_url=request.images_url,
            tenant_id=user.tenant_id,
        )

        return resp_200(data=answer_payload(answer))
    except Exception as e:
        return resp_500(code=500, message=str(e))


@router.delete("/answers/{answer_id}")
async def delete_answer(
    answer_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: AnswerService = Depends(get_answer_service),
):
    """删除回答"""
    try:
        success = await service.delete_answer(answer_id, user.user_id)
        return resp_200(data={"success": success})
    except BaseErrorCode as exc:
        return exc.return_resp_instance()
    except Exception as e:
        return resp_500(code=500, message=str(e))


# ==================== 评论管理 Endpoints ====================


async def get_comment_service() -> CommentService:
    """依赖注入：评论服务"""
    return CommentService()


@router.post("/comments", response_model=CommentDetailResponse)
async def create_comment(
    request: CommentCreateRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: CommentService = Depends(get_comment_service),
):
    """发布评论/追问"""
    if not user.user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    comment = await service.create_comment(user.user_id, user.user_name, request)
    if not isinstance(comment, dict):
        comment = await service.attach_author(comment, user)
    return resp_200(data=comment_payload(comment))


@router.post("/admin/moderate-delete")
async def moderate_delete(
    request: ModerateDeleteRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """平台超管违规删除问题/回答/评论/追问：先删内容，再按 R* 扣分（失败入补扣队列）。"""
    try:
        result = await ModerateDeleteService().moderate_delete(
            operator=user,
            target_type=request.target_type,  # type: ignore[arg-type]
            target_id=request.target_id,
            rule_code=request.rule_code,
            remark=request.remark,
        )
        return resp_200(
            data={
                "deleted": result.deleted,
                "target_type": result.target_type,
                "target_id": result.target_id,
                "target_user_id": result.target_user_id,
                "deducted": result.deducted,
                "pending_deduct": result.pending_deduct,
                "reason": result.reason,
            }
        )
    except BaseErrorCode as exc:
        return exc.return_resp_instance()
    except Exception as e:
        logger.exception("qa.moderate_delete.failed")
        return resp_500(code=500, message=str(e))


@router.post(
    "/allcomments",
)
async def get_allcomments(
    request: GetCommentsRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: CommentService = Depends(get_comment_service),
):
    """获取回答的评论"""
    comments, total = await service.get_comments(
        request.answer_id,
        request.question_id,
        (request.page - 1) * request.page_size,
        request.page_size,
        user=user,
    )
    page_data = CommentPageData(
        comments=[CommentDetailResponse.from_comment(comment) for comment in comments],
        total=total,
    )
    return resp_200(data=dump_qa_datetimes(page_data.model_dump()))


# ==================== 投票 Endpoints ====================


async def get_vote_service() -> VoteService:
    """依赖注入：投票服务"""
    return VoteService()


@router.post("/votes/question", response_model=dict)
async def vote_question(
    request: VoteRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: VoteService = Depends(get_vote_service),
):
    """给问题点赞"""
    if not user.user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    success = await service.vote_question(user.user_id, request.target_id)
    return resp_200(data={"success": success})


@router.post("/votes/answer", response_model=dict)
async def vote_answer(
    request: VoteRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: VoteService = Depends(get_vote_service),
):
    """给回答点赞（有用）"""
    if not user.user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    success = await service.vote_answer(user.user_id, request.target_id)
    return resp_200(data={"success": success})


# ==================== 通知 Endpoints ====================


@router.get("/notifications", response_model=list[QANotificationResponse])
async def get_notifications(
    unread_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """获取通知列表"""
    from bisheng.qa_expert.domain.repositories import NotificationRepository

    repo = NotificationRepository()
    notifications, total = await repo.get_user_notifications(
        user.user_id, unread_only=unread_only, skip=skip, limit=limit
    )

    return resp_200(data={"notifications": [_jsonable(item) for item in notifications], "total": total})


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """标记通知为已读"""
    from bisheng.qa_expert.domain.repositories import NotificationRepository

    repo = NotificationRepository()
    success = await repo.mark_as_read(notification_id)

    return resp_200(data={"success": success})


# ==================== 公共方法 ====================


@router.get("/assets/watermarked-download")
async def download_watermarked_asset(
    source: str = Query(..., description="问答图片或附件地址"),
    title: str = Query("", description="原始文件名"),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """将专家问答上传的图片/附件转为带水印 PDF 后下载。"""
    from urllib.parse import quote

    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.qa_expert.domain.watermarked_download import (
        QaWatermarkDownloadError,
        build_watermarked_qa_pdf,
    )

    storage = await get_minio_storage()
    user_name = str(getattr(user, "user_name", "") or user.user_id)
    try:
        payload, filename = await build_watermarked_qa_pdf(
            source=source,
            title=title,
            user_name=user_name,
            account=user_name,
            department_name="",
            tenant_id=get_current_tenant_id(),
            storage=storage,
        )
    except QaWatermarkDownloadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("QA watermarked download failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="水印下载失败") from exc

    # HTTP 头须 latin-1；中文文件名走 RFC 5987 filename*
    encoded_filename = quote(filename, safe="")
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (f"attachment; filename=\"qa-asset.pdf\"; filename*=UTF-8''{encoded_filename}"),
        },
    )


@router.post("/upload")
async def upload_file(*, file: UploadFile = File(...)):
    try:
        file_name = file.filename

        uuid_file_name = await KnowledgeService.save_upload_file_original_name(file_name)

        file_path = await save_uploaded_file(
            file,
            "bisheng",
            uuid_file_name,
            content_type=infer_qa_content_type(uuid_file_name, file.content_type),
        )

        if not isinstance(file_path, str):
            file_path = str(file_path)
        storage = await get_minio_storage()

        return resp_200(
            UploadFileResponse(
                file_path=file_path,
                relative_path=f"{storage.tmp_bucket}/{uuid_file_name}",
                file_name=file_name,
            )
        )

    except Exception as e:
        logger.error(f"File upload failed: {e}")
        raise ServerError(msg=f"File upload failed: {e}")

    finally:
        await file.close()


async def get_publish_service():
    """依赖注入：转公开服务"""
    from bisheng.qa_expert.domain.publish_service import PublishService

    return PublishService()


def _jsonable(row):
    """把 SQLModel/Pydantic 转成可进 UnifiedResponse 的 dict，时间带 +08:00。"""
    dump = getattr(row, "model_dump", None)
    if callable(dump):
        try:
            payload = dump()
        except TypeError:
            payload = dump()
        return dump_qa_datetimes(payload)
    return dump_qa_datetimes(row)


@router.post("/questions/{question_id}/publish-requests")
async def create_publish_request(
    question_id: int,
    request: PublishCreateRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service=Depends(get_publish_service),
):
    """发起转公开申请"""
    row = await service.create_publish_request(question_id, user, request.duration_days)
    return resp_200(data=_jsonable(row))


@router.post("/publish-requests/{request_id}/approve")
async def approve_publish_request(
    request_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service=Depends(get_publish_service),
):
    """同意转公开"""
    row = await service.decide_publish(request_id, user, "approved")
    return resp_200(data=_jsonable(row))


@router.post("/publish-requests/{request_id}/reject")
async def reject_publish_request(
    request_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service=Depends(get_publish_service),
):
    """拒绝转公开"""
    row = await service.decide_publish(request_id, user, "rejected")
    return resp_200(data=_jsonable(row))


@router.get("/publish-requests/{request_id}")
async def get_publish_request(
    request_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service=Depends(get_publish_service),
):
    """读取转公开申请（读时惰性过期）"""
    row = await service.get_request(request_id, user)
    return resp_200(data=_jsonable(row))
