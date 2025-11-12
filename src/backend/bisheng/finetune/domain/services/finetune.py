import asyncio
import io
import json
from typing import Dict, List, Any

from loguru import logger
from pydantic import ValidationError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.finetune import (CancelJobError, ChangeModelNameError, CreateFinetuneError,
                                             DeleteJobError, ExportJobError, InvalidExtraParamsError, JobStatusError,
                                             ModelNameExistsError, NotFoundJobError,
                                             TrainDataNoneError, UnExportJobError, GetModelError)
from bisheng.common.errcode.model_deploy import NotFoundModelError
from bisheng.common.errcode.server import NoSftServerError
from bisheng.common.schemas.api import UnifiedResponseModel
from bisheng.core.cache import InMemoryCache
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync, get_minio_storage
from ..models.finetune import (Finetune, FinetuneChangeModelName, FinetuneDao,
                               FinetuneExtraParams, FinetuneList, FinetuneStatus)
from ..models.model_deploy import ModelDeploy, ModelDeployDao, ModelDeployInfo
from ..models.server import Server, ServerDao
from ..models.sft_model import SftModelDao
from ..sft_backend import SFTBackend
from ...utils import parse_gpus, parse_server_host


class FinetuneService:
    ServerCache: InMemoryCache = InMemoryCache()

    @classmethod
    def validate_params(cls, finetune: Finetune) -> UnifiedResponseModel | None:
        """ 检查请求参数，返回None表示校验通过 """
        # 个人训练集和预置训练集 最少使用一个
        if not finetune.train_data and not finetune.preset_data:
            raise TrainDataNoneError()
        try:
            # 校验额外参数值
            FinetuneExtraParams(**finetune.extra_params.copy())
        except ValidationError as e:
            logger.error(f'Finetune extra_params is invalid {e}')
            raise InvalidExtraParamsError()
        return None

    @classmethod
    def parse_command_params(cls, finetune: Finetune, base_model: ModelDeploy) -> Dict:
        """ 解析请求参数，组合成训练指令的command参数 """
        params = finetune.extra_params.copy()
        # 需要在SFT-backend服务将model_name转为模型所在的绝对路径
        params['model_name_or_path'] = base_model.model
        params['model_template'] = finetune.root_model_name
        params['finetuning_type'] = finetune.method

        # 特殊处理cpu_load的格式，因为传参方式不一样 --cpu_load 即代表为True，无需额外参数值
        if params.get('cpu_load') == 'false':
            del params['cpu_load']
        elif params.get('cpu_load') == 'true':
            params['cpu_load'] = ''

        # 拼接训练集参数
        params['dataset'] = []
        params['each_max_samples'] = []
        cls.parse_command_train_file(finetune.train_data, params)
        cls.parse_command_train_file(finetune.preset_data, params)
        params['dataset'] = ','.join(params['dataset'])
        params['each_max_samples'] = ','.join(params['each_max_samples'])
        return params

    @classmethod
    def parse_command_train_file(cls, train_data: List[Dict], params: Dict):
        """ 获取minio上文件的公开链接，以便SFT-Backend下载训练文件 """
        if train_data is None:
            return
        minio_client = get_minio_storage_sync()
        for i in train_data:
            params['dataset'].append(minio_client.get_share_link(i['url']))
            params['each_max_samples'].append(str(i.get('num', 0)))

    @classmethod
    def validate_status(cls, finetune: Finetune, new_status: int) -> None:
        """ 校验状态变更是否符合逻辑 返回None表示成功"""
        # 训练中 只能 变为训练成功、训练失败、任务中止
        if finetune.status == FinetuneStatus.TRAINING.value:
            if new_status not in [FinetuneStatus.SUCCESS.value, FinetuneStatus.FAILED.value,
                                  FinetuneStatus.CANCEL.value]:
                raise JobStatusError.http_exception(msg='训练中只能变为训练成功、训练失败、任务中止')
        # 训练失败 只能 变为训练中
        elif finetune.status == FinetuneStatus.FAILED.value:
            if new_status != FinetuneStatus.TRAINING.value:
                raise JobStatusError.http_exception(msg='训练失败只能变为训练中')
        # 任务中止 只能 变为训练中
        elif finetune.status == FinetuneStatus.CANCEL.value:
            if new_status != FinetuneStatus.TRAINING.value:
                raise JobStatusError.http_exception(msg='任务中止只能变为训练中')
        # 训练成功 只能 变为发布完成
        elif finetune.status == FinetuneStatus.SUCCESS.value:
            if new_status != FinetuneStatus.PUBLISHED.value:
                raise JobStatusError.http_exception(msg='训练成功只能变为发布完成')
        # 发布完成 只能 变为训练成功
        elif finetune.status == FinetuneStatus.PUBLISHED.value:
            if new_status != FinetuneStatus.SUCCESS.value:
                raise JobStatusError.http_exception(msg='发布完成只能变为训练成功')
        return None

    @classmethod
    async def get_sft_server(cls, server_id: int) -> Server | None:
        server = await cls.get_server_by_cache(server_id)
        if not server:
            logger.warning('not found rt server data by id: %s', server_id)
            return None
        if not server.sft_endpoint:
            logger.warning('not found sft endpoint by id: %s', server_id)
            return None
        return server

    @classmethod
    async def verify_job_model_name(cls, model_name: str) -> bool:
        """ 校验model_name 是否已存在 """
        if await ModelDeployDao.find_model_by_name(model_name):
            raise ModelNameExistsError()
        if await FinetuneDao.find_job_by_model_name(model_name):
            raise ModelNameExistsError()
        return True

    @classmethod
    async def create_job(cls, finetune: Finetune) -> Finetune:
        # 校验额外参数
        _ = cls.validate_params(finetune)

        # 查找SFT服务是否存在
        server = await cls.get_sft_server(finetune.server)
        if not server:
            raise NoSftServerError()

        # 校验模型名是否已存在
        await cls.verify_job_model_name(finetune.model_name)

        # 查找基础模型是否存在
        base_model = await ModelDeployDao.find_model(finetune.base_model)
        if not base_model:
            raise NotFoundModelError()
        root_model_name = base_model.model
        # 能找到说明是基于已训练完成的模型进行的再次训练
        if base_job := await FinetuneDao.find_job_by_model_name(base_model.model):
            root_model_name = base_job.root_model_name

        finetune.server_name = server.server
        finetune.rt_endpoint = server.endpoint
        finetune.sft_endpoint = server.sft_endpoint
        finetune.base_model_name = base_model.model
        finetune.root_model_name = root_model_name

        # 调用SFT-backend的API新建任务
        logger.info(f'start create sft job: {finetune.id}')
        # 拼接指令所需的command参数
        command_params = cls.parse_command_params(finetune, base_model)
        sft_ret = await SFTBackend.create_job(host=parse_server_host(finetune.sft_endpoint),
                                              job_id=finetune.id, params=command_params)
        if not sft_ret[0]:
            logger.error(f'create sft job error: job_id: {finetune.id}, err: {sft_ret[1]}')
            raise CreateFinetuneError()
        # 插入到数据库内
        finetune = await FinetuneDao.insert_one(finetune)
        logger.info('create sft job success')
        return finetune

    @classmethod
    async def cancel_job(cls, job_id: str, user: UserPayload) -> Finetune:
        # 查看job任务信息
        finetune = await FinetuneDao.find_job(job_id)
        if not finetune:
            raise NotFoundJobError()

        # 校验任务状态变化
        new_status = FinetuneStatus.CANCEL.value
        cls.validate_status(finetune, new_status)

        # 调用SFT-backend的API取消任务
        logger.info(f'start cancel job_id: {job_id}, user: {user.user_name}')
        sft_ret = await SFTBackend.cancel_job(host=parse_server_host(finetune.sft_endpoint), job_id=job_id)
        if not sft_ret[0]:
            logger.error(f'cancel sft job error: job_id: {job_id}, err: {sft_ret[1]}')
            raise CancelJobError()
        logger.info('change sft job status')
        await FinetuneDao.change_status(job_id, finetune.status, new_status)
        finetune.status = new_status
        logger.info('cancel sft job success')
        return finetune

    @classmethod
    async def delete_job(cls, job_id: str, user: UserPayload) -> Finetune:
        # 查看job任务信息
        finetune = await FinetuneDao.find_job(job_id)
        if not finetune:
            raise NotFoundJobError()

        model_name = await cls.delete_published_model(finetune)

        # 调用接口删除训练任务
        logger.info(f'start delete sft job: {job_id}, user: {user.user_name}')
        sft_ret = await SFTBackend.delete_job(host=parse_server_host(finetune.sft_endpoint), job_id=job_id,
                                              model_name=model_name)
        if not sft_ret[0]:
            logger.error(f'delete sft job error: job_id: {job_id}, err: {sft_ret[1]}')
            raise DeleteJobError()
        # 删除训练任务数据
        logger.info('delete sft job data')
        # 清理minio上的日志文件
        await FinetuneDao.delete_job(finetune)
        logger.info(f'delete sft job success, data: {finetune.model_dump()}')
        asyncio.create_task(cls.delete_job_log(finetune))
        return finetune

    @classmethod
    async def delete_job_log(cls, finetune: Finetune):
        minio_client = await get_minio_storage()
        await minio_client.remove_object(object_name=f'/finetune/log/{finetune.id}')

    @classmethod
    async def upload_job_log(cls, finetune: Finetune, log_data: io.BytesIO, length: int) -> str:
        minio_client = await get_minio_storage()
        log_path = f'finetune/log/{finetune.id}'
        await minio_client.put_object(bucket_name=minio_client.bucket, object_name=log_path, file=log_data,
                                      length=length)
        return log_path

    @classmethod
    async def get_job_log(cls, finetune: Finetune) -> str | None:
        minio_client = await get_minio_storage()
        resp = await minio_client.get_object(object_name=finetune.log_path)
        if resp is None:
            return None
        return resp.decode('utf-8')

    @classmethod
    async def delete_published_model(cls, finetune: Finetune) -> str | None:
        """
         下线已发布模型，删除已发布模型数据，返回已发布模型名称
         param finetune: 训练任务
        """
        # 判断训练任务状态
        if finetune.status != FinetuneStatus.PUBLISHED.value:
            return finetune.model_name
        # 查看已发布模型ID
        published_model = await ModelDeployDao.find_model(finetune.model_id)
        if not published_model:
            return finetune.model_name

        # 删除已发布模型数据
        await ModelDeployDao.delete_model(published_model)
        logger.info(f'delete published model: {published_model.model}, id: {published_model.id}')
        return published_model.model

    @classmethod
    async def publish_job(cls, job_id: str, user: UserPayload) -> Finetune:
        # 查看job任务信息
        finetune = await FinetuneDao.find_job(job_id)
        if not finetune:
            raise NotFoundJobError()
        new_status = FinetuneStatus.PUBLISHED.value
        cls.validate_status(finetune, new_status)

        # 调用SFT-backend的API接口
        logger.info(f'start export sft job: {job_id}, user: {user.user_name}')
        sft_ret = await SFTBackend.publish_job(host=parse_server_host(finetune.sft_endpoint), job_id=job_id,
                                               model_name=finetune.model_name)
        if not sft_ret[0]:
            logger.error(f'export sft job error: job_id: {job_id}, err: {sft_ret[1]}')
            raise ExportJobError()
        # 创建已发布模型数据
        logger.info('create published model')
        published_model = ModelDeploy(model=finetune.model_name,
                                      server=str(finetune.server),
                                      endpoint=f'http://{finetune.rt_endpoint}/v2.1/models')
        try:
            published_model = await ModelDeployDao.insert_one(published_model)
        except Exception as e:
            logger.error(f'create published model error: {str(e)}')
            published_model = await ModelDeployDao.find_model_by_server_and_name(published_model.server,
                                                                                 published_model.model)

        # 记录可用于训练的模型名称
        await SftModelDao.insert_sft_model(published_model.model)

        # 更新训练任务状态
        logger.info('update sft job data')
        finetune.status = new_status
        finetune.model_id = published_model.id
        await FinetuneDao.update_job(finetune)
        logger.info('export sft job success')
        return finetune

    @classmethod
    async def cancel_publish_job(cls, job_id: str, user: UserPayload) -> Finetune:
        # 查看job任务信息
        finetune = await FinetuneDao.find_job(job_id)
        if not finetune:
            raise NotFoundJobError()
        new_status = FinetuneStatus.SUCCESS.value
        cls.validate_status(finetune, new_status)

        await cls.delete_published_model(finetune)

        # 调用SFT-backend的API接口
        logger.info(f'start cancel export sft job: {job_id}, user: {user.user_name}')
        sft_ret = await SFTBackend.cancel_publish_job(host=parse_server_host(finetune.sft_endpoint), job_id=job_id,
                                                      model_name=finetune.model_name)
        if not sft_ret[0]:
            logger.error(f'cancel export sft job error: job_id: {job_id}, err: {sft_ret[1]}')
            raise UnExportJobError()
        await SftModelDao.delete_sft_model(finetune.model_name)
        # 删除发布的模型信息
        logger.info(f'delete published model: {finetune.model_id}')
        await ModelDeployDao.delete_model_by_id(finetune.model_id)
        logger.info('update finetune status')
        finetune.status = new_status
        finetune.model_id = 0
        await FinetuneDao.update_job(finetune)
        logger.info('cancel export sft job success')
        return finetune

    @classmethod
    async def get_server_by_cache(cls, server_id: int):
        # 先从内存获取
        cache_server = cls.ServerCache.get(server_id)
        if cache_server:
            return cls.ServerCache.get(server_id)
        # 再从数据库获取
        server = await ServerDao.find_server(server_id)
        if server:
            cls.ServerCache.set(server_id, server)
        return server

    @classmethod
    async def get_all_job(cls, req_data: FinetuneList) -> (List[Finetune], int):
        job_list, total = await FinetuneDao.find_jobs(req_data)
        # 异步线程更新任务状态
        asyncio.create_task(cls.sync_all_job_status(job_list))
        return job_list, total

    @classmethod
    async def sync_all_job_status(cls, job_list: List[Finetune]) -> None:
        # 异步线程更新批量任务的状态
        for finetune in job_list:
            await cls.sync_job_status(finetune, finetune.sft_endpoint)

    @classmethod
    async def get_job_info(cls, job_id: str) -> Dict[str, Any]:
        """ 获取训练中任务的实时信息 """
        # 查看job任务信息
        finetune = await FinetuneDao.find_job(job_id)
        if not finetune:
            raise NotFoundJobError()

        # 同步任务执行情况
        await cls.sync_job_status(finetune, finetune.sft_endpoint)

        # 获取日志文件
        log_data = None
        res_data = list()
        if finetune.log_path:
            log_data = await cls.get_job_log(finetune)
            res_data = cls.parse_log_data(log_data)

        return {
            'finetune': finetune,
            'log': log_data if finetune.status != FinetuneStatus.FAILED.value else finetune.reason,
            'loss_data': res_data,  # like [{"step": 10, "loss": 0.5}, {"step": 20, "loss": 0.3}]
            'report': finetune.report if finetune.report else None,
        }

    @classmethod
    def parse_log_data(cls, log_data: str) -> List[Dict[str, str]]:
        if log_data is None:
            return []
        res_data = []
        contents = log_data.split('\n')
        for elem in contents:
            if elem.strip() == '':
                continue
            sub_data = {'step': None, 'loss': None}
            elem = elem.strip()
            elem_data = json.loads(elem)
            if elem_data.get('loss', None) is None:
                continue
            sub_data['step'] = elem_data['current_steps']
            sub_data['loss'] = elem_data['loss']
            res_data.append(sub_data)
        return res_data

    @classmethod
    async def sync_job_status(cls, finetune: Finetune, sft_endpoint: str) -> bool:
        """ 从SFT-backend服务同步任务状态 """
        if finetune.status != FinetuneStatus.TRAINING.value:
            return True
        logger.info(f'start sync job status: {finetune.id}')

        sft_ret = await SFTBackend.get_job_status(host=parse_server_host(sft_endpoint), job_id=finetune.id)
        if not sft_ret[0]:
            logger.error(f'get sft job status error: job_id: {finetune.id}, err: {sft_ret[1]}')
            return False
        if sft_ret[1]['status'] == SFTBackend.JOB_FINISHED:
            finetune.status = FinetuneStatus.SUCCESS.value
            await FinetuneDao.change_status(finetune.id, finetune.status, FinetuneStatus.SUCCESS.value)
        elif sft_ret[1]['status'] == SFTBackend.JOB_FAILED:
            finetune.status = FinetuneStatus.FAILED.value
            finetune.reason = sft_ret[1]['reason']
            await FinetuneDao.update_job(finetune)

        # 执行失败无需查询日志和报告
        if finetune.status == FinetuneStatus.FAILED.value:
            logger.info('sft job status failed, no need exec log and report')
            return False

        # 查询任务执行日志和报告
        logger.info('start query sft job log and report')
        sft_ret = await SFTBackend.get_job_log(host=parse_server_host(sft_endpoint), job_id=finetune.id)
        if not sft_ret[0]:
            logger.error(f'get sft job log error: job_id: {finetune.id}, err: {sft_ret[1]}')
        log_data = sft_ret[1]['log_data'].encode('utf-8')
        # 上传日志文件到minio上
        log_path = await cls.upload_job_log(finetune, io.BytesIO(log_data), len(log_data))
        finetune.log_path = log_path

        # 查询任务评估报告
        logger.info('start query sft job report')
        sft_ret = await SFTBackend.get_job_metrics(host=parse_server_host(sft_endpoint), job_id=finetune.id)
        if not sft_ret[0]:
            logger.error(f'get sft job report error: job_id: {finetune.id}, err: {sft_ret[1]}')
        else:
            finetune.report = sft_ret[1]['report']

        # 更新日志和报告数据
        await FinetuneDao.update_job(finetune)
        return True

    @classmethod
    async def change_job_model_name(cls, req: FinetuneChangeModelName) -> Finetune:
        """ 修改训练任务的模型名称 """
        finetune = await FinetuneDao.find_job(req.id)
        if not finetune:
            raise NotFoundJobError()

        # 校验模型名是否已存在
        await cls.verify_job_model_name(req.model_name)

        # 修改已发布的模型名称
        if not await cls.change_published_model_name(finetune, req.model_name):
            raise ChangeModelNameError()

        # 更新训练任务的model_name
        finetune.model_name = req.model_name
        await FinetuneDao.update_job(finetune)

        return finetune

    @classmethod
    async def change_published_model_name(cls, finetune: Finetune, model_name: str) -> bool:
        """ 修改训练任务的模型名称 """
        # 未发布的训练任务无需操作对应的model
        if finetune.status != FinetuneStatus.PUBLISHED.value:
            return True
        published_model = await ModelDeployDao.find_model(finetune.model_id)
        if not published_model:
            logger.error(f'published model not found, job_id: {finetune.id}, model_id: {finetune.model_id}')
            return False

        # 调用接口修改已发布模型的名称
        sft_ret = await SFTBackend.change_model_name(parse_server_host(finetune.sft_endpoint), finetune.id,
                                                     published_model.model, model_name)
        if not sft_ret[0]:
            logger.error(f'change model name error: job_id: {finetune.id}, err: {sft_ret[1]}')
            return False

        # 修改可预训练的模型名称
        await SftModelDao.change_sft_model(published_model.model, model_name)

        # 更新已发布模型的model_name
        published_model.model = model_name
        await ModelDeployDao.update_model(published_model)
        return True

    @classmethod
    async def get_server_filters(cls) -> List[Dict[str, Any]]:
        """ 获取ft服务器过滤条件 """
        server_filters = await FinetuneDao.get_server_filters()
        res = []
        for one in server_filters:
            res.append({
                'id': one,
                'server_name': one,
            })
        return res

    @classmethod
    async def get_model_list(cls, server_id: int) -> List[ModelDeploy]:
        """ 获取ft服务下的所有模型列表 """
        server_info = await ServerDao.find_server(server_id)
        if not server_info:
            raise NoSftServerError()
        flag, model_name_list = await SFTBackend.get_all_model(parse_server_host(server_info.sft_endpoint))
        if not flag:
            logger.error(f'get model list error: server_id: {server_id}, err: {model_name_list}')
            raise GetModelError()
        ret = []
        db_model = await ModelDeployDao.find_model_by_server(str(server_id))
        for one in db_model:
            if one.model in model_name_list:
                ret.append(one)
                model_name_list.remove(one.model)
        for one in model_name_list:
            ret.append(await ModelDeployDao.insert_one(ModelDeploy(server=str(server_id),
                                                                   model=one,
                                                                   endpoint=f'http://{server_info.endpoint}/v2.1/models')))

        res = []
        for one in ret:
            res.append(ModelDeployInfo(**one.dict(), sft_support=True))
        return res

    @classmethod
    async def get_gpu_info(cls) -> List[Dict]:
        """ 获取GPU信息 """
        all_server = await ServerDao.find_all_server()
        res = []
        for server in all_server:
            if not server.sft_endpoint:
                continue
            sft_ret = await SFTBackend.get_gpu_info(parse_server_host(server.sft_endpoint))
            if not sft_ret[0]:
                logger.error(f'get gpu info error: server_id: {server.id}, err: {sft_ret[1]}')
                continue
            gpu_info = parse_gpus(sft_ret[1])
            for one in gpu_info:
                one['server'] = server.server
                res.append(one)
        return res
