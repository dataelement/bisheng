import json

from bisheng.api.v1.schemas import UnifiedResponseModel
from bisheng.database.models.finetune import Finetune, FinetuneCreate
from fastapi import APIRouter, Depends
from fastapi_jwt_auth import AuthJWT

router = APIRouter(prefix='/finetune', tags=['FineTune'])


# create finetune job
@router.post('/job', response_model=UnifiedResponseModel[Finetune])
async def create_finetune(*,
                          finetune: FinetuneCreate,
                          Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    print(current_user)
