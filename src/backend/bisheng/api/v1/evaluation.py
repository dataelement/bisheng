import json
from typing import List, Optional
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.base import session_getter
from bisheng.api.services.evaluation import EvaluationService
from bisheng.api.services.user_service import UserPayload
from fastapi import Form
from fastapi_jwt_auth import AuthJWT
from fastapi import APIRouter, Depends, Query, UploadFile
from bisheng.database.models.evaluation import EvaluationRead, EvaluationCreate, Evaluation

router = APIRouter(prefix='/evaluation', tags=['Skills'])


@router.get('', response_model=UnifiedResponseModel[List[Evaluation]])
def get_evaluation(*,
                   page: Optional[int] = Query(default=1, gt=0, description='页码'),
                   limit: Optional[int] = Query(default=10, gt=0, description='每页条数'),
                   Authorize: AuthJWT = Depends()):
    """ 获取评测任务列表. """
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**current_user)
    return EvaluationService.get_evaluation(user, page, limit)


@router.post('/create', response_model=UnifiedResponseModel[EvaluationRead], status_code=201)
def create_evaluation(*,
                      file: UploadFile,
                      prompt: str = Form(),
                      exec_type: str = Form(),
                      unique_id: str = Form(),
                      version: Optional[int] = Form(default=None),
                      authorize: AuthJWT = Depends()):
    """ 创建评测任务. """
    authorize.jwt_required()
    payload = json.loads(authorize.get_jwt_subject())
    user_id = payload.get('user_id')

    file_name, file_path = EvaluationService.upload_file(file=file)
    db_evaluation = Evaluation.model_validate(EvaluationCreate(unique_id=unique_id,
                                                               exec_type=exec_type,
                                                               version=version,
                                                               prompt=prompt,
                                                               user_id=user_id,
                                                               file_name=file_name,
                                                               file_path=file_path))
    with session_getter() as session:
        session.add(db_evaluation)
        session.commit()
        session.refresh(db_evaluation)
    return resp_200(db_evaluation.copy())
