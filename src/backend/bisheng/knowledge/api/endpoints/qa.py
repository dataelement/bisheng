from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.domain.services.qa_recall_service import QaRecallService

router = APIRouter(prefix="/qa", tags=["QA"], dependencies=[Depends(UserPayload.get_login_user)])


@router.get("/keyword")
async def get_answer_keyword(
    message_id: Annotated[int, Query(gt=0)],
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(await QaRecallService.keywords(login_user, message_id))


@router.post("/chunk", status_code=200)
async def get_original_file(
    message_id: Annotated[int, Body(embed=True, gt=0)],
    keys: Annotated[str, Body(embed=True, max_length=4096)],
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(await QaRecallService.original_files(login_user, message_id, keys))
