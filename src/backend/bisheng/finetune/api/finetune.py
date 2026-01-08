import json
import tempfile
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Query, UploadFile
from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200, PageData
from bisheng.core.cache.utils import async_file_download
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.finetune.domain.models.finetune import Finetune, FinetuneChangeModelName, FinetuneList
from bisheng.finetune.domain.services.finetune import FinetuneService
from bisheng.finetune.domain.services.finetune_file import FinetuneFileService
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import QAKnoweldgeDao
from ..schemas import FinetuneCreateReq

router = APIRouter(prefix='/finetune', tags=['Finetune'], dependencies=[Depends(UserPayload.get_login_user)])


# create finetune job
@router.post('/job')
async def create_job(*, finetune: FinetuneCreateReq, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # get login user
    finetune = Finetune(**finetune.model_dump(exclude={'method'}),
                        method=finetune.method.value,
                        user_id=login_user.user_id,
                        user_name=login_user.user_name)
    ret = await FinetuneService.create_job(finetune)
    return resp_200(ret)


# Delete training task
@router.delete('/job')
async def delete_job(*, job_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # get login user
    await FinetuneService.delete_job(job_id, login_user)
    return resp_200(None)


# Abort training mission
@router.post('/job/cancel')
async def cancel_job(*, job_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # get login user
    ret = await FinetuneService.cancel_job(job_id, login_user)
    return resp_200(ret)


# Publish Training Tasks
@router.post('/job/publish')
async def publish_job(*, job_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # get login user
    ret = await FinetuneService.publish_job(job_id, login_user)
    return resp_200(ret)


@router.post('/job/publish/cancel')
async def cancel_publish_job(*, job_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # get login user
    ret = await FinetuneService.cancel_publish_job(job_id, login_user)
    return resp_200(ret)


# Get a list of training tasks, support pagination
@router.get('/job')
async def get_job(*,
                  server: str = Query(default=None, description='RelatedRTService name'),
                  status: str = Query(
                      default='',
                      title='Multiple commas,separator',
                      description='the status of the training task,1: Training 2: Training failed 3: Task Aborted 4: Training Successful 5: Publication complete'),
                  model_name: Optional[str] = Query(default='', description='Model Name,Fuzzy search'),
                  page: Optional[int] = Query(default=1, description='Page'),
                  limit: Optional[int] = Query(default=10, description='Listings Per Page'),
                  login_user: UserPayload = Depends(UserPayload.get_login_user)):
    status_list = []
    if status.strip():
        status_list = [int(one) for one in status.strip().split(',')]
    req_data = FinetuneList(server_name=server,
                            status=status_list,
                            model_name=model_name,
                            page=page,
                            limit=limit)
    if not login_user.is_admin():
        req_data.user_id = login_user.user_id
    data, total = await FinetuneService.get_all_job(req_data)
    return resp_200(data=PageData(data=data, total=total))


# Get the latest details of the task, this interface will synchronize the querySFT-backendThe side updates the task status to the latest
@router.get('/job/info')
async def get_job_info(*, job_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # get login user
    ret = await FinetuneService.get_job_info(job_id)
    return resp_200(ret)


@router.patch('/job/model')
async def update_job(*, req_data: FinetuneChangeModelName,
                     login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # get login user
    ret = await FinetuneService.change_job_model_name(req_data)
    return resp_200(ret)


@router.post('/job/file')
async def upload_file(*,
                      files: list[UploadFile] = File(description='Training File List'),
                      login_user: UserPayload = Depends(UserPayload.get_login_user)):
    ret = await FinetuneFileService.upload_file(files, False, login_user)
    return resp_200(ret)


@router.post('/job/file/preset')
async def upload_preset_file(*,
                             files: Optional[str] = Body(default=None, description='Preset Training File List'),
                             name: Optional[str] = Body(description='Dataset Name'),
                             qa_list: Optional[list[int]] = Body(default=None,
                                                                 description='QAThe knowledge base upon'),
                             login_user: UserPayload = Depends(UserPayload.get_login_user)):
    ret = None
    if files:
        filepath, file_name = await async_file_download(files)
        logger.info(f'dataset upload_file_name: {file_name}')
        ret = await FinetuneFileService.upload_preset_file(name, 0, filepath, login_user)
    elif qa_list:
        # will beqaData byfinetuneFormat for file storage
        qa_knowledge_db = await KnowledgeDao.aget_list_by_ids(qa_list)
        qa_knowledge_db_ids = [qa_knowledge.id for qa_knowledge in qa_knowledge_db]
        qa_db_list = await QAKnoweldgeDao.aget_qa_knowledge_by_knowledge_ids(qa_knowledge_db_ids)
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
            ret = await FinetuneFileService.upload_preset_file(name, 1, filepath.name, login_user)
    return resp_200(ret)


# Get a list of preset training files
@router.get('/job/file/preset')
async def get_preset_file(*,
                          page_size: Optional[int] = None,
                          page_num: Optional[int] = None,
                          keyword: Optional[str] = None,
                          login_user: UserPayload = Depends(UserPayload.get_login_user)):
    ret = await FinetuneFileService.get_preset_file(keyword, page_size, page_num)
    return resp_200(ret)


@router.delete('/job/file/preset')
async def delete_preset_file(*, file_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # get login user
    await FinetuneFileService.delete_preset_file(file_id, login_user)
    return resp_200()


@router.get('/job/file/download')
async def get_download_url(*, file_url: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    minio_client = get_minio_storage_sync()
    download_url = await minio_client.get_share_link(file_url, clear_host=False)
    return resp_200(data={'url': download_url})


@router.get('/server/filters')
async def get_server_filters(*, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    ret = await FinetuneService.get_server_filters()
    return resp_200(data=ret)


@router.get('/model/list')
async def get_model_list(login_user: UserPayload = Depends(UserPayload.get_login_user),
                         server_id: int = Query(..., description='ftService UniqueID')):
    """ DapatkanftList of all models under the service """
    ret = await FinetuneService.get_model_list(server_id)
    return resp_200(data=ret)


@router.get('/gpu')
async def get_gpu_info(*, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # get login user
    ret = await FinetuneService.get_gpu_info()
    return resp_200(data=ret)
