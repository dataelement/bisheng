import json
import tempfile
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, Request
from fastapi_jwt_auth import AuthJWT

from bisheng.api.services.finetune import FinetuneService
from bisheng.api.services.finetune_file import FinetuneFileService
from bisheng.api.services.user_service import get_login_user, UserPayload
from bisheng.api.v1.schemas import FinetuneCreateReq, UnifiedResponseModel, resp_200
from bisheng.cache.utils import file_download
from bisheng.database.models.finetune import Finetune, FinetuneChangeModelName, FinetuneList
from bisheng.database.models.model_deploy import ModelDeploy
from bisheng.database.models.knowledge import KnowledgeDao
from bisheng.database.models.knowledge_file import QAKnoweldgeDao
from bisheng.database.models.preset_train import PresetTrain
from bisheng.utils.minio_client import MinioClient
from fastapi import APIRouter, Body, Depends, File, Query, UploadFile
from fastapi_jwt_auth import AuthJWT
from loguru import logger

router = APIRouter(prefix='/finetune', tags=['Finetune'], dependencies=[Depends(get_login_user)])


# create finetune job
@router.post('/job', response_model=UnifiedResponseModel[Finetune])
async def create_job(*, finetune: FinetuneCreateReq, Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    finetune = Finetune(**finetune.dict(exclude={'method'}),
                        method=finetune.method.value,
                        user_id=current_user.get('user_id'),
                        user_name=current_user.get('user_name'))
    return FinetuneService.create_job(finetune)


# 删除训练任务
@router.delete('/job', response_model=UnifiedResponseModel)
async def delete_job(*, job_id: UUID, Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    return FinetuneService.delete_job(job_id, current_user)


# 中止训练任务
@router.post('/job/cancel', response_model=UnifiedResponseModel)
async def cancel_job(*, job_id: UUID, Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    return FinetuneService.cancel_job(job_id, current_user)


# 发布训练任务
@router.post('/job/publish', response_model=UnifiedResponseModel)
async def publish_job(*, job_id: UUID, Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    return FinetuneService.publish_job(job_id, current_user)


@router.post('/job/publish/cancel', response_model=UnifiedResponseModel)
async def cancel_publish_job(*, job_id: UUID, Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    return FinetuneService.cancel_publish_job(job_id, current_user)


# 获取训练任务列表，支持分页
@router.get('/job', response_model=UnifiedResponseModel[List[Finetune]])
async def get_job(*,
                  server: str = Query(default=None, description='关联的RT服务名字'),
                  status: str = Query(
                      default='',
                      title='多个以英文逗号,分隔',
                      description='训练任务的状态，1: 训练中 2: 训练失败 3: 任务中止 4: 训练成功 5: 发布完成'),
                  model_name: Optional[str] = Query(default='', description='模型名称,模糊搜索'),
                  page: Optional[int] = Query(default=1, description='页码'),
                  limit: Optional[int] = Query(default=10, description='每页条数'),
                  Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    status_list = []
    if status.strip():
        status_list = [int(one) for one in status.strip().split(',')]
    req_data = FinetuneList(server_name=server,
                            status=status_list,
                            model_name=model_name,
                            page=page,
                            limit=limit)
    return FinetuneService.get_all_job(req_data)


# 获取任务最新详细信息，此接口会同步查询SFT-backend侧将任务状态更新到最新
@router.get('/job/info', response_model=UnifiedResponseModel[Finetune])
async def get_job_info(*, job_id: UUID, Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    return FinetuneService.get_job_info(job_id)


@router.patch('/job/model', response_model=UnifiedResponseModel)
async def update_job(*, req_data: FinetuneChangeModelName, Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    return FinetuneService.change_job_model_name(req_data, current_user)


@router.post('/job/file', response_model=UnifiedResponseModel[List[PresetTrain]])
async def upload_file(*,
                      files: list[UploadFile] = File(description='训练文件列表'),
                      Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())

    return FinetuneFileService.upload_file(files, False, current_user)


@router.post('/job/file/preset', response_model=UnifiedResponseModel[List[PresetTrain]])
async def upload_preset_file(*,
                             files: Optional[str] = Body(default=None, description='预置训练文件列表'),
                             name: Optional[str] = Body(description='数据集名字'),
                             qa_list: Optional[list[int]] = Body(default=None,
                                                                 description='QA知识库'),
                             Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    if files:
        filepath, file_name = file_download(files)
        logger.info(f'dataset upload_file_name: {file_name}')
        return FinetuneFileService.upload_preset_file(name, 0, filepath, current_user)
    elif qa_list:
        # 将qa数据按照finetune格式，进行文件存储
        qa_knowledge_db = KnowledgeDao.get_list_by_ids(qa_list)
        qa_knowledge_db_ids = [qa_knowledge.id for qa_knowledge in qa_knowledge_db]
        qa_db_list = QAKnoweldgeDao.get_qa_knowledge_by_knowledge_ids(qa_knowledge_db_ids)
        qa_list = []
        for qa in qa_db_list:
            qa_list.extend([{
                'instruction': question,
                'input': '',
                'output': json.loads(qa.answers)[0]
            } for question in qa.questions])
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.json') as filepath:
            json.dump(qa_list, filepath, ensure_ascii=False, indent=2)
            filepath.seek(0)
            return FinetuneFileService.upload_preset_file(name, 1, filepath.name, current_user)


# 获取预置训练文件列表
@router.get('/job/file/preset', response_model=UnifiedResponseModel[List[PresetTrain]])
async def get_preset_file(*,
                          page_size: Optional[int] = None,
                          page_num: Optional[int] = None,
                          keyword: Optional[str] = None,
                          Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    ret = FinetuneFileService.get_preset_file(keyword, page_size, page_num)
    return resp_200(ret)


@router.delete('/job/file/preset', response_model=UnifiedResponseModel)
async def delete_preset_file(*, file_id: UUID, Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    return FinetuneFileService.delete_preset_file(file_id, current_user)


@router.get('/job/file/download', response_model=UnifiedResponseModel)
async def get_download_url(*, file_url: str, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    minio_client = MinioClient()
    download_url = minio_client.get_share_link(file_url)
    return resp_200(data={'url': download_url})


@router.get('/server/filters', response_model=UnifiedResponseModel)
async def get_server_filters(*, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()

    return FinetuneService.get_server_filters()


@router.get('/model/list', response_model=UnifiedResponseModel[List[ModelDeploy]])
async def get_model_list(request: Request,
                         login_user: UserPayload = Depends(get_login_user),
                         server_id: int = Query(..., description='ft服务唯一ID')):
    """ 获取ft服务下所有的模型列表 """
    ret = FinetuneService.get_model_list(login_user, server_id)
    return resp_200(data=ret)


@router.get('/gpu', response_model=UnifiedResponseModel)
async def get_gpu_info(*, Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    return FinetuneService.get_gpu_info()
