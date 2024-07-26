from typing import List

from fastapi import APIRouter, Request, Depends

from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.schemas import UnifiedResponseModel, LLMServerInfo

router = APIRouter(prefix='/llm', tags=['LLM'])


@router.get('')
def get_all_llm(
        request: Request,
        login_user: UserPayload = Depends(get_login_user),
) -> UnifiedResponseModel[List[LLMServerInfo]]:
    pass
