import copy
import json
import time
from typing import Annotated, List, Optional, Union
from uuid import UUID

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request, UploadFile
from loguru import logger

from bisheng.api.v1.schemas import (ProcessResponse, UploadFileResponse,
                                    resp_200)
from bisheng.chat.utils import judge_source, process_source_document
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.server import SystemConfigEmptyError, SystemConfigInvalidError, UploadFileEmptyError, \
    UploadFileExtError
from bisheng.common.models.config import Config, ConfigDao, ConfigKeyEnum
from bisheng.common.schemas.telemetry.event_data_schema import NewMessageSessionEventData, ApplicationAliveEventData, \
    ApplicationProcessEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.cache.utils import save_uploaded_file, upload_file_to_minio
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.interface.types import get_all_types_dict
from bisheng.open_endpoints.domain.utils import get_default_operator_async
from bisheng.processing.process import process_graph_cached, process_tweaks
from bisheng.services.deps import get_session_service, get_task_service
from bisheng.services.task.service import TaskService
from bisheng.utils import generate_uuid
from bisheng.utils import get_request_ip

try:
    from bisheng.worker import process_graph_cached_task
except ImportError:

    def process_graph_cached_task(*args, **kwargs):
        raise NotImplementedError('Celery is not installed')

# build router
router = APIRouter(tags=['Base'])

if bisheng_settings.debug:
    import tracemalloc
    import os
    import threading


    @router.get("/tracemalloc")
    def tracemalloc_point():
        snapshot = tracemalloc.take_snapshot()
        process_id = os.getpid()
        thread_id = threading.get_ident()
        snapshot.dump(f"/app/data/snapshot_{process_id}_{thread_id}_{time.time()}.prof")

        return resp_200()


@router.get('/all')
def get_all():
    """Get all parameters"""
    all_types = get_all_types_dict()
    return resp_200(all_types)


@router.get('/env')
def get_env():
    from bisheng import __version__
    """Get environment variable parameters"""
    uns_support = ['doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'txt', 'md', 'html', 'pdf', 'csv']

    etl_for_lm_url = bisheng_settings.get_knowledge().etl4lm.url
    if etl_for_lm_url:
        uns_support.extend(['png', 'jpg', 'jpeg', 'bmp'])

    env = {}
    if isinstance(bisheng_settings.environment, str):
        env['env'] = bisheng_settings.environment
    else:
        env = copy.deepcopy(bisheng_settings.environment)

    env['uns_support'] = uns_support
    if bisheng_settings.get_from_db('office_url'):
        env['office_url'] = bisheng_settings.get_from_db('office_url')
    # add tips from settings
    env['dialog_tips'] = bisheng_settings.get_from_db('dialog_tips')
    # add env dict from settings
    env.update(bisheng_settings.get_from_db('env') or {})
    env['pro'] = bisheng_settings.get_system_login_method().bisheng_pro
    env['version'] = __version__
    env['enable_etl4lm'] = bool(etl_for_lm_url)

    return resp_200(env)


@router.get('/config')
def get_config(admin_user: UserPayload = Depends(UserPayload.get_admin_user)):
    db_config = ConfigDao.get_config(ConfigKeyEnum.INIT_DB)
    config_str = db_config.value if db_config else ''
    return resp_200(config_str)


@router.post('/config/save')
def save_config(data: dict, admin_user: UserPayload = Depends(UserPayload.get_admin_user)):
    if not data.get('data', '').strip():
        raise SystemConfigEmptyError()
    try:
        # Check for complianceyamlFormat
        config = yaml.safe_load(data.get('data'))

        # Judging linsight_invitation_code Right?boolean
        if isinstance(config, dict) and 'linsight_invitation_code' in config.keys():
            if config['linsight_invitation_code'] is not None and bool(config['linsight_invitation_code']) not in [True,
                                                                                                                   False]:
                raise ValueError('linsight_invitation_code must be a boolean value')

        db_config = ConfigDao.get_config(ConfigKeyEnum.INIT_DB)
        db_config.value = data.get('data')
        ConfigDao.insert_config(db_config)
        get_redis_client_sync().delete('config:initdb_config')
    except Exception as e:
        raise SystemConfigInvalidError()

    return resp_200()


@router.get('/web/config')
async def get_web_config():
    """ Get some configuration items required by the front-end, the content is determined by the front-end """
    web_conf = ConfigDao.get_config(ConfigKeyEnum.WEB_CONFIG)
    if not web_conf:
        return resp_200(data='')
    return resp_200(data={'value': web_conf.value})


@router.post('/web/config')
async def update_web_config(request: Request,
                            admin_user: UserPayload = Depends(UserPayload.get_admin_user),
                            value: str = Body(embed=True)):
    """ Update some configuration items required by the front-end, the content is determined by the front-end """
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
        task_service: TaskService = Depends(get_task_service),
        sync: Annotated[bool, Body(embed=True)] = True,
):
    return await process_flow(flow_id, inputs, tweaks, history_count, clear_cache, session_id,
                              task_service, sync)


# For backwards compatibility we will keep the old endpoint
# @router.post('/predict/{flow_id}')
@router.post('/process')
async def process_flow(
        flow_id: Annotated[UUID, Body(embed=True)],
        inputs: Optional[dict] = None,
        tweaks: Optional[dict] = None,
        history_count: Annotated[int, Body(embed=True)] = 10,
        clear_cache: Annotated[bool, Body(embed=True)] = False,  # noqa: F821
        session_id: Annotated[Union[None, str], Body(embed=True)] = None,  # noqa: F821
        task_service: TaskService = Depends(get_task_service),
        sync: Annotated[bool, Body(embed=True)] = True,  # noqa: F821
        sse: Annotated[bool, Body(embed=True)] = False,
):
    """
    Endpoint to process an input with a given flow_id.
    """
    if inputs and isinstance(inputs, dict) and 'id' in inputs:
        inputs.pop('id')
    flow_id = flow_id.hex
    logger.info(
        f'act=api_call sessionid={session_id} flow_id={flow_id} inputs={inputs} tweaks={tweaks}')

    login_user = await get_default_operator_async()
    flow = await FlowDao.aget_flow_by_id(flow_id)
    if flow is None or flow.data is None:
        raise NotFoundError()
    start_time = time.time()
    if session_id is None:
        # Generate a session ID
        session_id = get_session_service().generate_key(session_id=session_id,
                                                        data_graph=flow.data)
    try:
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
        # Judgment traceability
        source_documents = task_result.pop('source_documents', '')
        answer = list(task_result.values())[0]
        extra = {}
        source, result = await judge_source(answer, source_documents, session_id, extra)

        try:
            question = ChatMessage(user_id=login_user.user_id,
                                   is_bot=False,
                                   type='end',
                                   chat_id=session_id,
                                   category='question',
                                   flow_id=flow_id,
                                   message=json.dumps(inputs))
            message = ChatMessage(user_id=login_user.user_id,
                                  is_bot=True,
                                  chat_id=session_id,
                                  flow_id=flow_id,
                                  type='end',
                                  category='answer',
                                  message=answer,
                                  source=source)
            ChatMessageDao.insert_one(question)
            message = ChatMessageDao.insert_one(message)
            try:
                MessageSessionDao.insert_one(
                    MessageSession(
                        chat_id=session_id,
                        flow_id=flow_id,
                        flow_name=flow.name,
                        flow_type=FlowType.FLOW.value,
                        user_id=login_user.user_id,
                    ))

                # RecordTelemetryJournal
                await telemetry_service.log_event(user_id=login_user.user_id,
                                                  event_type=BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION,
                                                  trace_id=trace_id_var.get(),
                                                  event_data=NewMessageSessionEventData(
                                                      session_id=session_id,
                                                      app_id=flow_id,
                                                      source='api',
                                                      app_name=flow.name,
                                                      app_type=ApplicationTypeEnum.SKILL
                                                  )
                                                  )
            except Exception as e:
                logger.warning(f'insert repeat session error: {e}')

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
    finally:
        end_time = time.time()
        await telemetry_service.log_event(user_id=login_user.user_id,
                                          event_type=BaseTelemetryTypeEnum.APPLICATION_ALIVE,
                                          trace_id=trace_id_var.get(),
                                          event_data=ApplicationAliveEventData(
                                              app_id=flow_id,
                                              app_name=flow.name,
                                              app_type=ApplicationTypeEnum.SKILL,
                                              chat_id=session_id,
                                              start_time=int(start_time),
                                              end_time=int(end_time)))
        await telemetry_service.log_event(user_id=login_user.user_id,
                                          event_type=BaseTelemetryTypeEnum.APPLICATION_PROCESS,
                                          trace_id=trace_id_var.get(),
                                          event_data=ApplicationProcessEventData(
                                              app_id=flow_id,
                                              app_name=flow.name,
                                              app_type=ApplicationTypeEnum.SKILL,
                                              chat_id=session_id,
                                              start_time=int(start_time),
                                              end_time=int(end_time),
                                              process_time=int((end_time - start_time) * 1000)
                                          ))


async def _upload_file(file: UploadFile, object_name_prefix: str, file_supports: List[str] = None,
                       bucket_name: str = None) \
        -> UploadFileResponse:
    if file.size == 0:
        raise UploadFileEmptyError()
    file_ext = file.filename.split('.')[-1].lower()
    if file_supports and file_ext not in file_supports:
        raise UploadFileExtError()
    object_name = f'{object_name_prefix}/{generate_uuid()}.png'
    file_path = await upload_file_to_minio(file, object_name=object_name, bucket_name=bucket_name)
    if not isinstance(file_path, str):
        file_path = str(file_path)

    return UploadFileResponse(
        file_path=file_path,  # minioAccessible links
        relative_path=object_name,  # miniohitting the nail on the headobject_name
    )


@router.post('/upload/icon')
async def upload_icon(request: Request,
                      login_user: UserPayload = Depends(UserPayload.get_login_user),
                      file: UploadFile = None):
    bucket = bisheng_settings.object_storage.minio.public_bucket
    resp = await _upload_file(file,
                              object_name_prefix='icon',
                              file_supports=['jpeg', 'jpg', 'png'],
                              bucket_name=bucket)
    return resp_200(data=resp)


@router.post('/upload/workflow/{workflow_id}')
async def upload_icon_workflow(request: Request,
                               login_user: UserPayload = Depends(UserPayload.get_login_user),
                               file: UploadFile = None,
                               workflow_id: str = Path(..., description='workflow id')):
    bucket = bisheng_settings.object_storage.minio.public_bucket
    resp = await _upload_file(file, object_name_prefix=f'workflow/{workflow_id}', bucket_name=bucket)
    return resp_200(data=resp)


@router.post('/upload/{flow_id}')
async def create_upload_file(file: UploadFile, flow_id: str):
    # Cache file
    try:
        if len(file.filename) > 80:
            file.filename = file.filename[-80:]
        file_path = await save_uploaded_file(file, folder_name=flow_id, file_name=file.filename)
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
    from bisheng import __version__
    return resp_200({'version': __version__})
