import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import List

import requests
from bisheng.database.base import get_session
from bisheng.database.models.model_deploy import (ModelDeploy, ModelDeployQuery, ModelDeployRead, ModelDeployUpdate)
from bisheng.database.models.server import Server, ServerCreate, ServerRead
from bisheng.utils.logger import logger
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlmodel import select

# build router
router = APIRouter(prefix='/server', tags=['server'])

thread_pool = ThreadPoolExecutor(3)
required_param = ['type', 'pymodel_type', 'gpu_memory', 'instance_groups']


@router.post('/add', response_model=ServerRead, status_code=201)
async def add_server(*, session=Depends(get_session), server: ServerCreate):
    try:
        db_server = Server.from_orm(server)
        session.add(db_server)
        session.commit()
        session.refresh(db_server)
        # 拉取模型
        await update_model(db_server.endpoint, db_server.server)
        return db_server
    except Exception as exc:
        session.rollback()
        logger.error(f'Error add server: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get('/list', response_model=List[ModelDeployRead], status_code=201)
async def list(*, session=Depends(get_session), query: ModelDeployQuery = None):
    try:
        # 更新模型
        servers = session.exec(select(Server)).all()
        for server in servers:
            await update_model(server.endpoint, server.server)
        sql = select(ModelDeploy)
        if query and query.server:
            sql = sql.where(ModelDeploy.server == query.server)

        db_model = session.exec(sql.order_by(ModelDeploy.model)).all()
        return [jsonable_encoder(model) for model in db_model]
    except Exception as exc:
        logger.error(f'Error add server: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post('/update', response_model=ModelDeployRead, status_code=201)
async def update_deploy(*, session=Depends(get_session), deploy: ModelDeployUpdate):
    try:

        db_deploy = session.get(ModelDeploy, deploy.id)
        if not db_deploy:
            raise HTTPException(status_code=404, detail='配置不存在')

        deploy_data = deploy.dict(exclude_unset=True)
        for key, value in deploy_data.items():
            setattr(db_deploy, key, value)
        session.add(db_deploy)
        session.commit()
        session.refresh(db_deploy)
        return db_deploy
    except Exception as exc:
        logger.error(f'Error add server: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post('/load', status_code=201)
async def load(*, session=Depends(get_session), deploy_id: dict):
    db_deploy = session.get(ModelDeploy, deploy_id.get('deploy_id'))
    if not db_deploy:
        raise HTTPException(status_code=404, detail='配置不存在')
    try:
        endpoint = db_deploy.endpoint.replace('http://', '').split('/')[0]
        url = f'http://{endpoint}/v2/repository/models/{db_deploy.model}/load'
        data = db_deploy.config
        # #validator config
        config = json.loads(data)
        for key in required_param:
            if key not in config.get('parameters').keys() or not config.get('parameters')[key]:
                # 不OK
                raise Exception(f'必传参数{key}未传')
        # 先设置为上线中
        logger.info(f'load_model=success url={url} config={data}')
        db_deploy.status = '上线中'
        session.add(db_deploy)
        session.commit()
        session.refresh(db_deploy)
        # 真正开始执行load
        asyncio.get_event_loop().run_in_executor(thread_pool, load_model, url, data, deploy_id.get('deploy_id'))
        return {'message': 'load success'}
    except Exception as exc:
        logger.error(f'Error load model: {exc}')
        db_deploy.status = '异常'
        db_deploy.remark = error_translate(str(exc))
        session.add(db_deploy)
        session.commit()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post('/unload', status_code=201)
async def unload(*, session=Depends(get_session), deploy_id: dict):
    try:
        # 缓存本地
        db_deploy = session.get(ModelDeploy, deploy_id.get('deploy_id'))
        if not db_deploy:
            raise HTTPException(status_code=404, detail='配置不存在')
        endpoint = db_deploy.endpoint.replace('http://', '').split('/')[0]
        url = f'http://{endpoint}/v2/repository/models/{db_deploy.model}/unload'
        resp = requests.post(url)
        logger.info(f'unload_model=success url={url} code={resp.status_code}')
        # 更新状态
        db_deploy.status = '下线中'
        session.add(db_deploy)
        session.commit()
        session.refresh(db_deploy)
        return {'message': 'unload success'}

    except Exception as exc:
        logger.error(f'Error add server: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get('/GPU', status_code=200)
async def get_gpu(*, session=Depends(get_session)):
    try:
        # 缓存本地
        db_service = session.exec(select(Server)).all()
        if not db_service:
            raise HTTPException(status_code=404, detail='配置不存在')

        resp = []
        for service in db_service:
            ip = service.endpoint.split(':')[0]
            url = f'http://{ip}:9002/metrics'
            gpu = await queryGPU(url)
            logger.info(f'gpu_get=success url={url} gpu={gpu}')
            service.gpu = json.dumps(gpu)
            session.add(service)
            [g.update({'server': service.server}) for g in gpu]
            resp.append(gpu)
        session.commit()

        return {'data': {'list': resp}}

    except Exception as exc:
        logger.error(f'Error add server: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def load_model(url: str, data: str, deploy_id: int):
    response = requests.post(url, data=data)
    if response.status_code == 200:
        logger.info(f'load_model={url} result=success')
    else:
        logger.error(f'load_model=fail code={response.status_code}, return={response.text}')
        session = next(get_session())
        db_deploy = session.get(ModelDeploy, deploy_id)
        db_deploy.status = '异常'
        reason = json.loads(response.text).get('error')
        db_deploy.remark = error_translate(reason)
        session.add(db_deploy)
        session.commit()
        session.refresh(db_deploy)


pattern = r'gpu_uuid="([^"]+)"'


async def queryGPU(query_url: str):
    resp = requests.get(query_url)
    if resp.status_code != 200:
        return []
    content = resp.text
    lines = content.split('\n')
    gpus = []
    utility = {}
    device_dict = {}
    total_mem = {}
    used_mem = {}
    for line in lines:
        if '#' in line:
            continue

        if 'nv_gpu_utilization' in line:
            # nv_gpu_utilization{gpu_uuid="GPU-c8a73d12-b320-0910-68f1-a74bd0d626bd"}
            match = re.search(pattern, line)
            gpu_uuid = match.group(1) if match else None
            utility[gpu_uuid] = line.split(' ')[1]

        if 'nv_gpu_uuid_to_deviceid' in line:
            match = re.search(pattern, line)
            gpu_uuid = match.group(1) if match else None
            device_dict[gpu_uuid] = line.split(' ')[1]

        if 'nv_gpu_memory_total_bytes' in line:
            match = re.search(pattern, line)
            gpu_uuid = match.group(1) if match else None
            total_mem[gpu_uuid] = int(line.split(' ')[1].strip()) / 1024 / 1024 / 1024

        if 'nv_gpu_memory_used_bytes' in line:
            match = re.search(pattern, line)
            gpu_uuid = match.group(1) if match else None
            used_mem[gpu_uuid] = int(line.split(' ')[1].strip()) / 1024 / 1024 / 1024
    # 整理最终对象
    for uuid, deviceid in device_dict.items():
        gpu_res = {}
        gpu_res['gpu_id'] = deviceid
        gpu_res['gpu_uuid'] = uuid
        gpu_res['gpu_total_mem'] = '%.2f G' % (total_mem[uuid])
        gpu_res['gpu_used_mem'] = '%.2f G' % (total_mem[uuid] - used_mem[uuid])
        gpu_res['gpu_utility'] = utility[uuid]
        gpus.append(gpu_res)
    gpus = sorted(gpus, key=lambda x: x['gpu_id'])
    return gpus


async def update_model(endpoint: str, server: str):
    try:
        url = f'http://{endpoint}/v2/repository/index'
        resp = requests.post(url)
        if resp.status_code != 200:
            return []
        content = resp.text
    except Exception as e:
        logger.error(str(e))
        return

    session = next(get_session())
    db_deploy = session.exec(select(ModelDeploy).where(ModelDeploy.server == server)).all()
    model_dict = {deploy.model: deploy for deploy in db_deploy}
    for model in json.loads(content):
        model_name = model['name']
        status = model.get('state')
        reason = model.get('reason')
        if model_name in model_dict:
            db_model = model_dict.get(model_name)
        else:
            db_model = ModelDeploy(server=server, endpoint=f'http://{endpoint}/v2.1/models', model=model_name)

        # 当前是上下线中，需要判断
        origin_status = db_model.status
        if status == 'READY' and origin_status == '上线中':
            db_model.status = '已上线'
        if status == 'UNAVAILABLE':
            if reason == 'unloaded' and origin_status == '下线中':
                db_model.status = '未上线'
            elif reason != 'unloaded':
                db_model.status = '异常'
                db_model.remark = error_translate(reason)
        logger.debug(
            f'update_status={model_name} rt_status={status} db_status={origin_status} now_status={db_model.status}')
        if not db_model.config:
            # 初始化config
            config_url = f'http://{endpoint}/v2/repository/models/{model_name}/config'
            resp = requests.post(config_url)
            db_model.config = resp.text

        session.add(db_model)
    session.commit()


def error_translate(err: str):
    if 'OutOfMemoryError' in err:
        reason = f"上线失败，显卡{err.split('(')[1].split(';')[0]}显存不足"
    else:
        reason = f'上线失败，{err}'

    return reason
