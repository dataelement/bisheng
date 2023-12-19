import copy
import json
from typing import Optional

import yaml
from bisheng import settings
from bisheng.api.v1 import knowledge
from bisheng.api.v1.schemas import ProcessResponse, UploadFileResponse
from bisheng.cache.redis import redis_client
from bisheng.cache.utils import save_uploaded_file
from bisheng.database.base import get_session
from bisheng.database.models.config import Config
from bisheng.database.models.flow import Flow
from bisheng.interface.types import langchain_types_dict
from bisheng.processing.process import process_graph_cached, process_tweaks
from bisheng.settings import parse_key
from bisheng.utils.logger import logger
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi_jwt_auth import AuthJWT
from sqlalchemy import delete
from sqlmodel import Session, select

# build router
router = APIRouter(tags=['Base'])


@router.get('/all')
def get_all():
    return langchain_types_dict


@router.get('/env')
def getn_env():
    uns_support = ['png', 'jpg', 'jpeg', 'bmp', 'doc', 'docx', 'ppt',
                   'pptx', 'xls', 'xlsx', 'txt', 'md', 'html', 'pdf']
    env = {}
    if isinstance(settings.settings.environment, str):
        env['env'] = settings.settings.environment
    else:
        env = copy.deepcopy(settings.settings.environment)
    if settings.settings.get_knowledge().get('unstructured_api_url'):
        if not env.get('uns_support'):
            env['uns_support'] = uns_support
    else:
        env['uns_support'] = list(knowledge.filetype_load_map.keys())
    return {'data': env}


@router.get('/config')
def get_config(session: Session = Depends(get_session), Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    if payload.get('role') != 'admin':
        raise HTTPException(status_code=500, detail='Unauthorized')
    configs = session.exec(select(Config)).all()
    config_str = []
    for config in configs:
        config_str.append(config.key + ':')
        config_str.append(config.value)
    return '\n'.join(config_str)


@router.post('/config/save')
def save_config(data: dict, session: Session = Depends(get_session)):
    try:
        config_yaml = yaml.safe_load(data.get('data'))
        old_config = session.exec(select(Config).where(Config.id > 0)).all()
        session.exec(delete(Config).where(Config.id > 0))
        session.flush()
        keys = list(config_yaml.keys())
        values = parse_key(keys, data.get('data'))

        for index, key in enumerate(keys):
            config = Config(key=key, value=values[index])
            session.add(config)
        session.commit()
        # 淘汰缓存
        for old in old_config:
            redis_key = 'config_' + old.key
            redis_client.delete(redis_key)
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f'格式不正确, {str(e)}')

    return {'message': 'save success'}


# For backwards compatibility we will keep the old endpoint
@router.post('/predict/{flow_id}', response_model=ProcessResponse)
@router.post('/process/{flow_id}', response_model=ProcessResponse)
async def process_flow(
        flow_id: str,
        inputs: Optional[dict] = None,
        tweaks: Optional[dict] = None,
        session: Session = Depends(get_session),
):
    """
    Endpoint to process an input with a given flow_id.
    """
    if inputs and isinstance(inputs, dict):
        inputs.pop('id')

    try:
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
        response = process_graph_cached(graph_data, inputs)
        return ProcessResponse(result=response,)
    except Exception as e:
        # Log stack trace
        logger.exception(e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post('/upload/{flow_id}', response_model=UploadFileResponse, status_code=201)
async def create_upload_file(file: UploadFile, flow_id: str):
    # Cache file
    try:
        file_path = save_uploaded_file(file.file, folder_name=flow_id)

        return UploadFileResponse(
            flowId=flow_id,
            file_path=file_path,
        )
    except Exception as exc:
        logger.error(f'Error saving file: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# get endpoint to return version of bisheng
@router.get('/version')
def get_version():
    from bisheng import __version__

    return {'version': __version__}
