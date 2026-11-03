from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, StringConstraints

from bisheng.chat_session.application.answer_correction import AnswerCorrectionService
from bisheng.chat_session.domain.models.answer_correction import AnswerCorrection
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200

router = APIRouter(prefix="/answer-corrections")
LoginUser = Annotated[UserPayload, Depends(UserPayload.get_login_user)]
RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

FeedbackView = Literal["mine", "owner", "assigned"]

PUBLIC_FIELDS = {
    "id", "answer_id", "quote", "correction", "evidence", "state", "reply", "created_at", "updated_at",
}


class SubmitFeedback(BaseModel):
    answer_id: int
    quote: RequiredText
    correction: RequiredText
    evidence: RequiredText


def feedback_detail(record: AnswerCorrection, view: FeedbackView) -> dict:
    fields = PUBLIC_FIELDS
    if view != "mine":
        fields = fields | {"app_id", "knowledge_id", "assignee_id", "result"}
    return record.model_dump(include=fields)


@router.get("/eligibility/{answer_id}")
async def eligibility(answer_id: int, user: LoginUser):
    answer = await AnswerCorrectionService.eligible_answer(answer_id, user)
    return resp_200({"eligible": answer is not None})


@router.post("/")
async def submit_feedback(payload: SubmitFeedback, user: LoginUser):
    record = await AnswerCorrectionService.submit(**payload.model_dump(), user=user)
    return resp_200(feedback_detail(record, "mine"))


class Assignment(BaseModel):
    knowledge_id: int
    assignee_id: int


class ProcessingResult(BaseModel):
    result: RequiredText


class FeedbackReply(BaseModel):
    reply: RequiredText


@router.get("/{record_id}")
async def get_feedback(record_id: int, view: FeedbackView, user: LoginUser):
    record = await AnswerCorrectionService.detail(record_id, view, user)
    return resp_200(feedback_detail(record, view))


@router.post("/{record_id}/assignment")
async def assign_feedback(record_id: int, payload: Assignment, user: LoginUser):
    record = await AnswerCorrectionService.change(record_id, "assignment", user, **payload.model_dump())
    return resp_200(feedback_detail(record, "owner"))


@router.post("/{record_id}/result")
async def record_result(record_id: int, payload: ProcessingResult, user: LoginUser):
    record = await AnswerCorrectionService.change(record_id, "result", user, text=payload.result)
    return resp_200(feedback_detail(record, "assigned"))


@router.post("/{record_id}/reply")
async def reply_to_feedback(record_id: int, payload: FeedbackReply, user: LoginUser):
    record = await AnswerCorrectionService.change(record_id, "reply", user, text=payload.reply)
    return resp_200(feedback_detail(record, "owner"))


@router.get("/")
async def list_feedback(
    view: FeedbackView,
    user: LoginUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    items, total = await AnswerCorrectionService.list_feedback(view, user, page, page_size)
    return resp_200({"items": [feedback_detail(item, view) for item in items], "total": total})


@router.get("/{record_id}/knowledge-options")
async def knowledge_options(record_id: int, user: LoginUser):
    return resp_200({"items": await AnswerCorrectionService.knowledge_options(record_id, user)})


@router.get("/{record_id}/assignee-options")
async def assignee_options(
    record_id: int,
    knowledge_id: int,
    user: LoginUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    items, total = await AnswerCorrectionService.assignee_options(record_id, knowledge_id, user, page, page_size)
    return resp_200({"items": items, "total": total})
