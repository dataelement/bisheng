import json
import io
from typing import List, Optional
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200, resp_500
from bisheng.database.base import session_getter
from bisheng.api.services.evaluation import EvaluationService, add_evaluation_task
from bisheng.api.services.user_service import UserPayload, get_login_user
from fastapi_jwt_auth import AuthJWT
from fastapi import APIRouter, Depends, Query, UploadFile, Form, BackgroundTasks
from bisheng.database.models.evaluation import EvaluationRead, EvaluationCreate, Evaluation
from bisheng.utils.minio_client import MinioClient
from bisheng.cache.utils import convert_encoding_cchardet

router = APIRouter(prefix='/evaluation', tags=['Skills'], dependencies=[Depends(get_login_user)])


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


@router.post('', response_model=UnifiedResponseModel[EvaluationRead], status_code=201)
def create_evaluation(*,
                      file: UploadFile,
                      prompt: str = Form(),
                      exec_type: str = Form(),
                      unique_id: str = Form(),
                      version: Optional[int] = Form(default=None),
                      background_tasks: BackgroundTasks,
                      authorize: AuthJWT = Depends()):
    """ 创建评测任务. """
    authorize.jwt_required()
    payload = json.loads(authorize.get_jwt_subject())
    user_id = payload.get('user_id')

    try:
        # 尝试做下转码操作
        output_file = io.BytesIO()
        file.file = convert_encoding_cchardet(file.file, output_file)
        EvaluationService.parse_csv(file_data=io.BytesIO(file.file.read()))
    except ValueError:
        return resp_500(code=400, message='文件格式不符合要求，请参考模板文件')
    finally:
        file.file.seek(0)

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

    background_tasks.add_task(add_evaluation_task, evaluation_id=db_evaluation.id)

    return resp_200(db_evaluation.copy())


@router.delete('/{evaluation_id}', status_code=200)
def delete_evaluation(*, evaluation_id: int, Authorize: AuthJWT = Depends()):
    """ 删除评测任务（逻辑删除）. """
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**current_user)
    return EvaluationService.delete_evaluation(evaluation_id, user_payload=user)


@router.get('/result/file/download', response_model=UnifiedResponseModel)
async def get_download_url(*,
                           file_url: str,
                           Authorize: AuthJWT = Depends()):
    """ 获取文件下载地址. """
    Authorize.jwt_required()
    minio_client = MinioClient()
    download_url = minio_client.get_share_link(file_url)
    return resp_200(data={
        'url': download_url
    })


@router.post('/{evaluation_id}/process', status_code=200)
def delete_evaluation(*, evaluation_id: int, background_tasks: BackgroundTasks, Authorize: AuthJWT = Depends()):
    """ 手动执行评测任务. """
    Authorize.jwt_required()
    background_tasks.add_task(add_evaluation_task, evaluation_id=evaluation_id)
    return resp_200()
