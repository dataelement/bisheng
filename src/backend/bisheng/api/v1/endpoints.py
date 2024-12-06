import copy
import json
from typing import Annotated, List, Optional, Union
from uuid import UUID

import yaml
from bisheng import __version__, settings
from bisheng.api.services.knowledge_imp import filetype_load_map
from bisheng.api.services.user_service import UserPayload, get_admin_user, get_login_user
from bisheng.api.utils import get_request_ip
from bisheng.api.v1.schemas import (ProcessResponse, UnifiedResponseModel, UploadFileResponse,
                                    resp_200)
from bisheng.cache.redis import redis_client
from bisheng.cache.utils import save_uploaded_file, upload_file_to_minio
from bisheng.chat.utils import judge_source, process_source_document
from bisheng.database.base import generate_uuid, session_getter
from bisheng.database.models.config import Config, ConfigDao, ConfigKeyEnum
from bisheng.database.models.flow import Flow
from bisheng.database.models.message import ChatMessage
from bisheng.interface.types import get_all_types_dict
from bisheng.processing.process import process_graph_cached, process_tweaks
from bisheng.services.deps import get_session_service, get_task_service
from bisheng.services.task.service import TaskService
from bisheng.utils.logger import logger
from bisheng.utils.minio_client import MinioClient, bucket
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request, UploadFile
from sqlmodel import select

try:
    from bisheng.worker import process_graph_cached_task
except ImportError:

    def process_graph_cached_task(*args, **kwargs):
        raise NotImplementedError('Celery is not installed')


# build router
router = APIRouter(tags=['Base'])


@router.get('/all')
def get_all():
    """获取所有参数"""
    return resp_200(get_all_types_dict())


@router.get('/env')
def get_env():
    """获取环境变量参数"""
    uns_support = [
        'png', 'jpg', 'jpeg', 'bmp', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'txt', 'md',
        'html', 'pdf'
    ]
    env = {}
    if isinstance(settings.settings.environment, str):
        env['env'] = settings.settings.environment
    else:
        env = copy.deepcopy(settings.settings.environment)
    if settings.settings.get_knowledge().get('unstructured_api_url'):
        if not env.get('uns_support'):
            env['uns_support'] = uns_support
    else:
        env['uns_support'] = list(filetype_load_map.keys())
    if settings.settings.get_from_db('office_url'):
        env['office_url'] = settings.settings.get_from_db('office_url')
    # add tips from settings
    env['dialog_tips'] = settings.settings.get_from_db('dialog_tips')
    # add env dict from settings
    env.update(settings.settings.get_from_db('env') or {})
    env['pro'] = settings.settings.get_system_login_method().bisheng_pro
    env['version'] = __version__
    return resp_200(env)


@router.get('/config')
def get_config(admin_user: UserPayload = Depends(get_admin_user)):
    with session_getter() as session:
        config = session.exec(select(Config).where(Config.key == 'initdb_config')).first()
    if config:
        config_str = config.value
    else:
        config_str = ''
    return resp_200(config_str)


@router.post('/config/save')
def save_config(data: dict, admin_user: UserPayload = Depends(get_admin_user)):
    if not data.get('data', '').strip():
        raise HTTPException(status_code=500, detail='配置不能为空')
    try:
        # 校验是否符合yaml格式
        _ = yaml.safe_load(data.get('data'))
        with session_getter() as session:
            config = session.exec(select(Config).where(Config.key == 'initdb_config')).first()
            config.value = data.get('data')
            session.add(config)
            session.commit()
        redis_client.delete('config:initdb_config')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'格式不正确, {str(e)}')

    return resp_200('保存成功')


@router.get('/web/config')
async def get_web_config():
    """ 获取一些前端所需要的配置项，内容由前端决定 """
    web_conf = ConfigDao.get_config(ConfigKeyEnum.WEB_CONFIG)
    if not web_conf:
        return resp_200(data='')
    return resp_200(data={'value': web_conf.value})


@router.post('/web/config')
async def update_web_config(request: Request,
                            admin_user: UserPayload = Depends(get_admin_user),
                            value: str = Body(embed=True)):
    """ 更新一些前端所需要的配置项，内容由前端决定 """
    logger.info(
        f'update_web_config user_name={admin_user.user_name}, ip={get_request_ip(request)}')
    web_conf = ConfigDao.get_config(ConfigKeyEnum.WEB_CONFIG)
    if not web_conf:
        web_conf = Config(key=ConfigKeyEnum.WEB_CONFIG.value, value=value)
    else:
        web_conf.value = value
    ConfigDao.insert_config(web_conf)
    return resp_200(data={'value': web_conf.value})


@router.post('/process/{flow_id}')
async def process_flow_old(
    flow_id: UUID,
    inputs: Optional[dict] = None,
    tweaks: Optional[dict] = None,
    history_count: Annotated[int, Body(embed=True)] = 10,
    clear_cache: Annotated[bool, Body(embed=True)] = False,  # noqa: F821
    session_id: Annotated[Union[None, str], Body(embed=True)] = None,  # noqa: F821
    task_service: 'TaskService' = Depends(get_task_service),
    sync: Annotated[bool, Body(embed=True)] = True,
):
    return await process_flow(flow_id, inputs, tweaks, history_count, clear_cache, session_id,
                              task_service, sync)


# For backwards compatibility we will keep the old endpoint
# @router.post('/predict/{flow_id}', response_model=UnifiedResponseModel[ProcessResponse])
@router.post('/process', response_model=UnifiedResponseModel[ProcessResponse])
async def process_flow(
    flow_id: Annotated[UUID, Body(embed=True)],
    inputs: Optional[dict] = None,
    tweaks: Optional[dict] = None,
    history_count: Annotated[int, Body(embed=True)] = 10,
    clear_cache: Annotated[bool, Body(embed=True)] = False,  # noqa: F821
    session_id: Annotated[Union[None, str], Body(embed=True)] = None,  # noqa: F821
    task_service: 'TaskService' = Depends(get_task_service),
    sync: Annotated[bool, Body(embed=True)] = True,  # noqa: F821
    sse: Annotated[bool, Body(embed=True)] = False,
):
    """
    Endpoint to process an input with a given flow_id.
    """
    if inputs and isinstance(inputs, dict) and 'id' in inputs:
        inputs.pop('id')

    logger.info(
        f'act=api_call sessionid={session_id} flow_id={flow_id} inputs={inputs} tweaks={tweaks}')
    flow_id = flow_id.hex

    try:
        with session_getter() as session:
            flow = session.get(Flow, flow_id)
        if flow is None:
            raise ValueError(f'Flow {flow_id} not found')
        if flow.data is None:
            raise ValueError(f'Flow {flow_id} has no data')

        graph_data = flow.data
        if tweaks:
            try:
                graph_data = process_tweaks(graph_data, tweaks)
            except Exception as exc:
                logger.error(f'Error processing tweaks: {exc}')

        # process
        if sync:
            result = await process_graph_cached(graph_data,
                                                inputs,
                                                clear_cache,
                                                session_id,
                                                history_count=history_count,
                                                flow_id=flow_id)
            if isinstance(result, dict) and 'result' in result:
                task_result = result['result']
                session_id = result['session_id']
            elif hasattr(result, 'result') and hasattr(result, 'session_id'):
                task_result = result.result
                session_id = result.session_id
        else:
            logger.warning('This is an experimental feature and may not work as expected.'
                           'Please report any issues to our GitHub repository.')
            if session_id is None:
                # Generate a session ID
                session_id = get_session_service().generate_key(session_id=session_id,
                                                                data_graph=graph_data)
            task_id, task = await task_service.launch_task(
                process_graph_cached_task if task_service.use_celery else process_graph_cached,
                graph_data,
                inputs,
                clear_cache,
                session_id,
                history_count=history_count,
                flow_id=flow_id)
            if task.status == 'SUCCESS':
                task_result = task.result
                if hasattr(task_result, 'result'):
                    task_result = task_result.result
            else:
                logger.error(f'task_id={task_id} exception task result={task}')

        if isinstance(task_result, str):
            task_result = {'answer': task_result}
        # 判断溯源
        source_documents = task_result.pop('source_documents', '')
        answer = list(task_result.values())[0]
        extra = {}
        source, result = await judge_source(answer, source_documents, session_id, extra)

        try:
            question = ChatMessage(user_id=0,
                                   is_bot=False,
                                   type='end',
                                   chat_id=session_id,
                                   category='question',
                                   flow_id=flow_id,
                                   message=json.dumps(inputs))
            message = ChatMessage(user_id=0,
                                  is_bot=True,
                                  chat_id=session_id,
                                  flow_id=flow_id,
                                  type='end',
                                  category='answer',
                                  message=answer,
                                  source=source)
            with session_getter() as session:
                session.add_all([question, message])
                session.commit()
                session.refresh(message)

            extra.update({'source': source, 'message_id': message.id})

            if source == 1:
                await process_source_document(source_documents, session_id, message.id, answer)
                extra.update({
                    'source_url':
                    'resouce/{chat_id}/{msg_id}'.format(chat_id=session_id, msg_id=message.id)
                })
            elif source == 4:
                # QA
                extra_qa = json.loads(answer.metadata.get('extra'))
                extra_qa.pop('answer', None)
                extra.update({'doc': [extra_qa]})
            task_result.update(extra)
            task_result.update({'answer': result})
        except Exception as e:
            logger.error(e)

        return resp_200(
            ProcessResponse(
                result=task_result,
                # task=task_response,
                session_id=session_id,
                backend=task_service.backend_name,
            ))

    except Exception as e:
        # Log stack trace
        logger.exception(e)
        raise HTTPException(status_code=500, detail=str(e)) from e


def _upload_file(file: UploadFile, object_name_prefix: str, file_supports: List[str] = None, bucket_name: str = None) \
        -> UploadFileResponse:
    if file.size == 0:
        raise HTTPException(status_code=500, detail='上传文件不能为空')
    file_ext = file.filename.split('.')[-1].lower()
    if file_supports and file_ext not in file_supports:
        raise HTTPException(status_code=500, detail='仅支持 JPEG 和 PNG 格式的图片')
    try:
        object_name = f'{object_name_prefix}/{generate_uuid()}.png'
        file_path = upload_file_to_minio(file, object_name=object_name, bucket_name=bucket_name)
        if not isinstance(file_path, str):
            file_path = str(file_path)
        return UploadFileResponse(
            file_path=MinioClient.clear_minio_share_host(file_path),  # minio可访问的链接
            relative_path=object_name,  # minio中的object_name
        )
    except Exception as exc:
        logger.exception(f'Error saving file: {str(exc)}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post('/upload/icon')
async def upload_icon(request: Request,
                      login_user: UserPayload = Depends(get_login_user),
                      file: UploadFile = None):
    resp = _upload_file(file,
                        object_name_prefix='icon',
                        file_supports=['jpeg', 'jpg', 'png'],
                        bucket_name=bucket)
    return resp_200(data=resp)


@router.post('/upload/workflow/{workflow_id}')
async def upload_icon_workflow(request: Request,
                               login_user: UserPayload = Depends(get_login_user),
                               file: UploadFile = None,
                               workflow_id: str = Path(..., description='workflow id')):
    resp = _upload_file(file, object_name_prefix=f'workflow/{workflow_id}', bucket_name=bucket)
    return resp_200(data=resp)


@router.post('/upload/{flow_id}',
             response_model=UnifiedResponseModel[UploadFileResponse],
             status_code=201)
async def create_upload_file(file: UploadFile, flow_id: str):
    # Cache file
    try:
        file_path = save_uploaded_file(file.file, folder_name=flow_id, file_name=file.filename)
        if not isinstance(file_path, str):
            file_path = str(file_path)
        return resp_200(UploadFileResponse(
            flowId=flow_id,
            file_path=file_path,
        ))
    except Exception as exc:
        logger.error(f'Error saving file: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# get endpoint to return version of bisheng
@router.get('/version')
def get_version():
    return resp_200({'version': __version__})
