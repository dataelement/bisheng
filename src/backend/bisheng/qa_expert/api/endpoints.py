"""
Expert QA API Endpoints - HTTP 路由处理层
"""

from typing import Optional
from fastapi import APIRouter, Body, Depends, File, HTTPException, Path, UploadFile, status, Query
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.api.v1.schemas import UploadFileResponse
from bisheng.common.errcode.http_error import ServerError
from bisheng.core.cache.utils import save_uploaded_file
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200, resp_500

from bisheng.sensitive_word.domain.schemas import SensitiveWordBusinessType
from bisheng.sensitive_word.domain.services.exceptions import ContentSafetyViolation
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import (
    SensitiveWordPolicyService,
)
from bisheng.qa_expert.domain.schemas import (
    ExpertCreateRequest,
    ExpertUpdateRequest,
    ExpertResponse,
    GetCommentsRequest,
    QuestionCreateRequest,
    QuestionDetailResponse,
    QuestionSimpleResponse,
    AnswerCreateRequest,
    AnswerDetailResponse,
    CommentCreateRequest,
    CommentDetailResponse,
    CommentPageData,
    QuestionUpdateRequest,
    VoteRequest,
    AdoptAnswerRequest,
    QANotificationResponse,
    QuestionListQuery,
    QuestionPageData,
    QuestionStatsResponse,
    QAExpertStatsResponse,
    QuestionCheckRequest,
)
from bisheng.qa_expert.domain.services import (
    ExpertService,
    QuestionService,
    AnswerService,
    CommentService,
    VoteService,
    QAExpertStatsService,
)
from bisheng.user_group.domain.services.user_group_service import UserGroupService

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
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    page: int = Query(0, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=500, description="每页数量"),
    service: ExpertService = Depends(get_expert_service),
):
    """列表查询专家"""
    skip = (page - 1) * limit
    experts, total = await service.list_experts(keyword=keyword, skip=skip, limit=limit)
    return resp_200(data={"experts": experts, "total": total})


# ==================== 专家管理 Endpoints (补全) ====================


@router.post("/experts", response_model=ExpertResponse)
async def create_expert(request: ExpertCreateRequest, service: ExpertService = Depends(get_expert_service)):
    """创建专家（管理员操作）"""
    try:
        expert = await service.create_expert(request)
        return resp_200(data=expert)
    except Exception as e:
        return resp_500(code=500, msg=str(e))


@router.put("/experts/{expert_id}", response_model=ExpertResponse)
async def update_expert(
    expert_id: int,
    request: ExpertUpdateRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: ExpertService = Depends(get_expert_service),
):
    """更新专家信息"""
    try:
        expert = await service.update_expert(expert_id, request)
        return resp_200(data=expert)
    except Exception as e:
        return resp_500(code=500, msg=str(e))


@router.delete("/experts/{expert_id}")
async def delete_expert(
    expert_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: ExpertService = Depends(get_expert_service),
):
    """删除专家"""
    try:
        success = await service.delete_expert(expert_id)
        if not success:
            return resp_500(code=500, msg="Failed to delete expert")
        return resp_200(data={"message": "Expert deleted successfully"})
    except Exception as e:
        return resp_500(code=500, msg=str(e))

@router.get("/experts/name/{expert_name}")
async def expertsinfo(
    expert_name: str,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: ExpertService = Depends(get_expert_service),
):
    """获取专家"""
   
    experinfo = await service.get_expertinfo(expert_name)
    return resp_200(data=experinfo)
  

@router.get("/experts/userid/{user_id}")
async def expertsinfo_id(
    user_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: ExpertService = Depends(get_expert_service),
):
    """获取专家"""
   
    experinfo = await service.get_expertinfobyid(user_id)
    return resp_200(data=experinfo)


# ==================== 问题管理 Endpoints ====================


async def get_question_service() -> QuestionService:
    """依赖注入：问题服务"""
    return QuestionService()


@router.post("/check_questions", response_model=QuestionDetailResponse)
async def check_question(
    request: QuestionCheckRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    result = SensitiveWordPolicyService.check_text(
        tenant_id=user.tenant_id,
        business_type=SensitiveWordBusinessType.KNOWLEDGE_SPACE_FILE_PARSE,
        text=request.check_text,
    )
    if result.enabled and result.hits:
        raise ContentSafetyViolation(result)
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

    question = await service.create_question(user.user_id, request, user.user_name)
    return resp_200(data=question)


@router.get("/questions", response_model=QuestionPageData)
async def list_questions(
    query: QuestionListQuery = Depends(),
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: QuestionService = Depends(get_question_service),
):
    """问题列表"""

    user_id = user.user_id if query.my_questions else None

    questions, total = await service.list_questions(
        business_domain=query.domain,
        status=query.status,
        sort_by=query.sort_by,
        user_id=user_id,
        skip=(query.page - 1) * query.page_size,
        limit=query.page_size,
    )

    return resp_200(
        data={
            "questions": questions,
            "total": total,
        }
    )


@router.put("/questions/{question_id}", response_model=ExpertResponse)
async def update_question(
    question_id: int,
    request: QuestionUpdateRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: ExpertService = Depends(get_question_service),
):
    """更新专家信息"""
   
    expert = await service.update_question(question_id, request)
    return resp_200(data=expert)


@router.get("/questions/{question_id}", response_model=QuestionDetailResponse)
async def get_question_detail(
    question_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: QuestionService = Depends(get_question_service),
):
    """获取问题详情"""
    question = await service.get_question_detail(question_id, user.user_id)
    return resp_200(data=question)


@router.post("/questions/{question_id}/adopt", response_model=QuestionDetailResponse)
async def adopt_answer(
    question_id: int,
    request: AdoptAnswerRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: QuestionService = Depends(get_question_service),
):
    """采纳最佳回答"""
  
    question = await service.adopt_answer(question_id, request.answer_id, user.user_id)
    return resp_200(data=question)


@router.delete("/questions/{question_id}")
async def delete_question(
    question_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: QuestionService = Depends(get_question_service),
):
    """删除回答"""
    try:
        success = await service.delete_question(question_id)

        return resp_200(data={"success": success})
    except Exception as e:
        return resp_500(code=500, msg=str(e))



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

    answer = await service.create_answer(user.user_id, request)
    return resp_200(data=answer)


# 根据问题id获取回答数据
@router.get("/answers/{question_id}", response_model=list[AnswerDetailResponse])
async def get_answers(
    question_id: int = Path(..., ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: AnswerService = Depends(get_answer_service),
):
    """获取问题的所有回答"""
    answers, total = await service.get_answers(question_id, (page - 1) * page_size, page_size)
    return resp_200(data={"answers": answers, "total": total})


@router.get("/questions/{question_id}/answers")
async def get_answersbyname(
    question_id: int = Path(..., ge=1),
    expert_name: Optional[str] = Query(None), 
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: AnswerService = Depends(get_answer_service),
):
    """获取问题的所有回答"""
    answers = await service.get_by_expertname(expert_name, question_id)
    return resp_200(data=answers)





@router.put("/answers/{answer_id}", response_model=AnswerDetailResponse)
async def update_answer(
    answer_id: int,
    request: AnswerCreateRequest,
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
        )

        return resp_200(data=answer)
    except Exception as e:
        return resp_500(code=500, msg=str(e))


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
    except Exception as e:
        return resp_500(code=500, msg=str(e))


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

    comment = await service.create_comment(user.user_id,user.user_name, request)

    return resp_200(data=comment)


@router.post("/allcomments", )
async def get_allcomments(
    request: GetCommentsRequest,
    _user: UserPayload = Depends(UserPayload.get_login_user),
    service: CommentService = Depends(get_comment_service),
):
    """获取回答的评论"""
    comments, total = await service.get_comments(
        request.answer_id,
        request.question_id,
        (request.page - 1) * request.page_size,
        request.page_size,
    )
    page_data = CommentPageData(
        comments=[CommentDetailResponse.from_comment(comment) for comment in comments],
        total=total,
    )
    return resp_200(data=page_data.model_dump(mode="json"))


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

    return resp_200(data={"notifications": notifications, "total": total})


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


@router.post("/upload")
async def upload_file(*, file: UploadFile = File(...)):
    try:
        file_name = file.filename

        uuid_file_name = await KnowledgeService.save_upload_file_original_name(file_name)

        file_path = await save_uploaded_file(file, "bisheng", uuid_file_name)

        if not isinstance(file_path, str):
            file_path = str(file_path)

        return resp_200(UploadFileResponse(file_path=file_path))

    except Exception as e:
        logger.error(f"File upload failed: {e}")
        raise ServerError(msg=f"File upload failed: {e}")

    finally:
        await file.close()
