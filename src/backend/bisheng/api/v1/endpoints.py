import copy
import time
from typing import List

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request, UploadFile
from loguru import logger

from bisheng.api.v1.schemas import (UploadFileResponse,
                                    resp_200)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.server import SystemConfigEmptyError, SystemConfigInvalidError, UploadFileEmptyError, \
    UploadFileExtError
from bisheng.common.models.config import Config, ConfigDao, ConfigKeyEnum
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.cache.utils import save_uploaded_file, upload_file_to_minio
from bisheng.interface.types import get_all_types_dict
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
    env['dashboard_pro'] = bisheng_settings.get_system_login_method().dashboard_pro
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
    try:
        bucket = bisheng_settings.object_storage.minio.public_bucket
        resp = await _upload_file(file,
                                  object_name_prefix='icon',
                                  file_supports=['jpeg', 'jpg', 'png'],
                                  bucket_name=bucket)
        return resp_200(data=resp)
    except Exception as e:
        raise e
    finally:
        await file.close()


@router.post('/upload/workflow/{workflow_id}')
async def upload_icon_workflow(request: Request,
                               login_user: UserPayload = Depends(UserPayload.get_login_user),
                               file: UploadFile = None,
                               workflow_id: str = Path(..., description='workflow id')):
    try:
        bucket = bisheng_settings.object_storage.minio.public_bucket
        resp = await _upload_file(file, object_name_prefix=f'workflow/{workflow_id}', bucket_name=bucket)
        return resp_200(data=resp)
    except Exception as e:
        raise e
    finally:
        await file.close()


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
    finally:
        await file.close()


# get endpoint to return version of bisheng
@router.get('/version')
def get_version():
    from bisheng import __version__
    return resp_200({'version': __version__})
