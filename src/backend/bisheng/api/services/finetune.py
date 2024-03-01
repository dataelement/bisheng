import asyncio
import io
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List
from uuid import UUID

from bisheng.api.errcode.finetune import (CancelJobError, ChangeModelNameError, CreateFinetuneError,
                                          DeleteJobError, ExportJobError, GetGPUInfoError,
                                          InvalidExtraParamsError, JobStatusError,
                                          ModelNameExistsError, NotFoundJobError,
                                          TrainDataNoneError, UnExportJobError)
from bisheng.api.errcode.model_deploy import NotFoundModelError
from bisheng.api.errcode.server import NoSftServerError
from bisheng.api.services.rt_backend import RTBackend
from bisheng.api.services.sft_backend import SFTBackend
from bisheng.api.utils import parse_gpus, parse_server_host
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.cache import InMemoryCache
from bisheng.database.models.finetune import (Finetune, FinetuneChangeModelName, FinetuneDao,
                                              FinetuneExtraParams, FinetuneList, FinetuneStatus)
from bisheng.database.models.model_deploy import ModelDeploy, ModelDeployDao
from bisheng.database.models.server import Server, ServerDao
from bisheng.database.models.sft_model import SftModelDao
from bisheng.utils.logger import logger
from bisheng.utils.minio_client import MinioClient
from pydantic import ValidationError

sync_job_thread_pool = ThreadPoolExecutor(3)


class FinetuneService:
    ServerCache: InMemoryCache = InMemoryCache()

    @classmethod
    def validate_params(cls, finetune: Finetune) -> UnifiedResponseModel | None:
        """ 检查请求参数，返回None表示校验通过 """
        # 个人训练集和预置训练集 最少使用一个
        if not finetune.train_data and not finetune.preset_data:
            return TrainDataNoneError.return_resp()
        try:
            # 校验额外参数值
            FinetuneExtraParams(**finetune.extra_params.copy())
        except ValidationError as e:
            logger.error(f'Finetune extra_params is invalid {e}')
            return InvalidExtraParamsError.return_resp()
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
        minio_client = MinioClient()
        for i in train_data:
            params['dataset'].append(minio_client.get_share_link(i['url']))
            params['each_max_samples'].append(str(i.get('num', 0)))

    @classmethod
    def validate_status(cls, finetune: Finetune, new_status: int) -> UnifiedResponseModel | None:
        """ 校验状态变更是否符合逻辑 返回None表示成功"""
        # 训练中 只能 变为训练成功、训练失败、任务中止
        if finetune.status == FinetuneStatus.TRAINING.value:
            if new_status not in [FinetuneStatus.SUCCESS.value, FinetuneStatus.FAILED.value,
                                  FinetuneStatus.CANCEL.value]:
                return JobStatusError.return_resp(msg='训练中只能变为训练成功、训练失败、任务中止')
        # 训练失败 只能 变为训练中
        elif finetune.status == FinetuneStatus.FAILED.value:
            if new_status != FinetuneStatus.TRAINING.value:
                return JobStatusError.return_resp(msg='训练失败只能变为训练中')
        # 任务中止 只能 变为训练中
        elif finetune.status == FinetuneStatus.CANCEL.value:
            if new_status != FinetuneStatus.TRAINING.value:
                return JobStatusError.return_resp(msg='任务中止只能变为训练中')
        # 训练成功 只能 变为发布完成
        elif finetune.status == FinetuneStatus.SUCCESS.value:
            if new_status != FinetuneStatus.PUBLISHED.value:
                return JobStatusError.return_resp(msg='训练成功只能变为发布完成')
        # 发布完成 只能 变为训练成功
        elif finetune.status == FinetuneStatus.PUBLISHED.value:
            if new_status != FinetuneStatus.SUCCESS.value:
                return JobStatusError.return_resp('发布完成只能变为训练成功')
        return None

    @classmethod
    def get_sft_server(cls, server_id: int) -> Server | None:
        server = cls.get_server_by_cache(server_id)
        if not server:
            logger.warning('not found rt server data by id: %s', server_id)
            return None
        if not server.sft_endpoint:
            logger.warning('not found sft endpoint by id: %s', server_id)
            return None
        return server

    @classmethod
    def verify_job_model_name(cls, model_name: str) -> bool:
        """ 校验model_name 是否已存在 """
        if ModelDeployDao.find_model_by_name(model_name):
            return False
        if FinetuneDao.find_job_by_model_name(model_name):
            return False
        return True

    @classmethod
    def create_job(cls, finetune: Finetune) -> UnifiedResponseModel[Finetune]:
        # 校验额外参数
        validate_ret = cls.validate_params(finetune)
        if validate_ret is not None:
            return validate_ret

        # 查找SFT服务是否存在
        server = cls.get_sft_server(finetune.server)
        if not server:
            return NoSftServerError.return_resp()

        # 校验模型名是否已存在
        if not cls.verify_job_model_name(finetune.model_name):
            return ModelNameExistsError.return_resp()

        # 查找基础模型是否存在
        base_model = ModelDeployDao.find_model(finetune.base_model)
        if not base_model:
            return NotFoundModelError.return_resp()
        root_model_name = base_model.model
        # 能找到说明是基于已训练完成的模型进行的再次训练
        if base_job := FinetuneDao.find_job_by_model_name(base_model.model):
            root_model_name = base_job.root_model_name

        finetune.server_name = server.server
        finetune.rt_endpoint = server.endpoint
        finetune.sft_endpoint = server.sft_endpoint
        finetune.base_model_name = base_model.model
        finetune.root_model_name = root_model_name

        # 调用SFT-backend的API新建任务
        logger.info(f'start create sft job: {finetune.id.hex}')
        # 拼接指令所需的command参数
        command_params = cls.parse_command_params(finetune, base_model)
        sft_ret = SFTBackend.create_job(host=parse_server_host(finetune.sft_endpoint),
                                        job_id=finetune.id.hex, params=command_params)
        if not sft_ret[0]:
            logger.error(f'create sft job error: job_id: {finetune.id.hex}, err: {sft_ret[1]}')
            return CreateFinetuneError.return_resp()
        # 插入到数据库内
        FinetuneDao.insert_one(finetune)
        logger.info('create sft job success')
        return resp_200(data=finetune)

    @classmethod
    def cancel_job(cls, job_id: UUID, user: Any) -> UnifiedResponseModel[Finetune]:
        # 查看job任务信息
        finetune = FinetuneDao.find_job(job_id)
        if not finetune:
            return NotFoundJobError.return_resp()

        # 校验任务状态变化
        new_status = FinetuneStatus.CANCEL.value
        validate_ret = cls.validate_status(finetune, new_status)
        if validate_ret is not None:
            return validate_ret

        # 调用SFT-backend的API取消任务
        logger.info(f'start cancel job_id: {job_id}, user: {user.get("user_name")}')
        sft_ret = SFTBackend.cancel_job(host=parse_server_host(finetune.sft_endpoint), job_id=job_id.hex)
        if not sft_ret[0]:
            logger.error(f'cancel sft job error: job_id: {job_id}, err: {sft_ret[1]}')
            return CancelJobError.return_resp()
        logger.info('change sft job status')
        FinetuneDao.change_status(job_id, finetune.status, new_status)
        finetune.status = new_status
        logger.info('cancel sft job success')
        return resp_200(data=finetune)

    @classmethod
    def delete_job(cls, job_id: UUID, user: Any) -> UnifiedResponseModel[Finetune]:
        # 查看job任务信息
        finetune = FinetuneDao.find_job(job_id)
        if not finetune:
            return NotFoundJobError.return_resp()

        model_name = cls.delete_published_model(finetune, finetune.rt_endpoint)

        # 调用接口删除训练任务
        logger.info(f'start delete sft job: {job_id}, user: {user.get("user_name")}')
        sft_ret = SFTBackend.delete_job(host=parse_server_host(finetune.sft_endpoint), job_id=job_id.hex,
                                        model_name=model_name)
        if not sft_ret[0]:
            logger.error(f'delete sft job error: job_id: {job_id}, err: {sft_ret[1]}')
            return DeleteJobError.return_resp()
        # 删除训练任务数据
        logger.info('delete sft job data')
        # 清理minio上的日志文件
        FinetuneDao.delete_job(finetune)
        logger.info(f'delete sft job success, data: {finetune.dict}')
        return resp_200(data=None)

    @classmethod
    def delete_job_log(cls, finetune: Finetune):
        minio_client = MinioClient()
        minio_client.delete_minio(f'/finetune/log/{finetune.id.hex}')

    @classmethod
    def upload_job_log(cls, finetune: Finetune, log_data: io.BytesIO, length: int) -> str:
        minio_client = MinioClient()
        log_path = f'finetune/log/{finetune.id.hex}'
        minio_client.upload_minio_file(log_path, log_data, length)
        return log_path

    @classmethod
    def get_job_log(cls, finetune: Finetune) -> str | None:
        minio_client = MinioClient()
        resp = minio_client.download_minio(finetune.log_path)
        if resp is None:
            return None
        new_data = io.BytesIO()
        for d in resp.stream(32 * 1024):
            new_data.write(d)
        resp.close()
        resp.release_conn()
        new_data.seek(0)
        return new_data.read().decode('utf-8')

    @classmethod
    def delete_published_model(cls, finetune: Finetune, rt_endpoint: str) -> str | None:
        """
         下线已发布模型，删除已发布模型数据，返回已发布模型名称
         param finetune: 训练任务
         param rt_endpoint: RT服务地址
        """
        # 判断训练任务状态
        if finetune.status != FinetuneStatus.PUBLISHED.value:
            return finetune.model_name
        # 查看已发布模型ID
        published_model = ModelDeployDao.find_model(finetune.model_id)
        if not published_model:
            return finetune.model_name
        if published_model.status == '已上线':
            # 调用RT接口下线模型
            ret = RTBackend.unload_model(parse_server_host(rt_endpoint), published_model.model)
            if ret[0] is False:
                logger.error(f'unload published model error: {published_model.model}, err: {ret[1]}')
            else:
                logger.info(f'unload published model: {published_model.model}, resp: {ret}')
        # 删除已发布模型数据
        ModelDeployDao.delete_model(published_model)
        logger.info(f'delete published model: {published_model.model}, id: {published_model.id}')
        return published_model.model

    @classmethod
    def publish_job(cls, job_id: UUID, user: Any) -> UnifiedResponseModel[Finetune]:
        # 查看job任务信息
        finetune = FinetuneDao.find_job(job_id)
        if not finetune:
            return NotFoundJobError.return_resp()
        new_status = FinetuneStatus.PUBLISHED.value
        validate_ret = cls.validate_status(finetune, new_status)
        if validate_ret is not None:
            return validate_ret

        # 调用SFT-backend的API接口
        logger.info(f'start export sft job: {job_id}, user: {user.get("user_name")}')
        sft_ret = SFTBackend.publish_job(host=parse_server_host(finetune.sft_endpoint), job_id=job_id.hex,
                                         model_name=finetune.model_name)
        if not sft_ret[0]:
            logger.error(f'export sft job error: job_id: {job_id}, err: {sft_ret[1]}')
            return ExportJobError.return_resp()
        # 创建已发布模型数据
        logger.info('create published model')
        published_model = ModelDeploy(model=finetune.model_name,
                                      server=str(finetune.server),
                                      endpoint=f'http://{finetune.rt_endpoint}/v2.1/models')
        try:
            published_model = ModelDeployDao.insert_one(published_model)
        except Exception as e:
            logger.error(f'create published model error: {e}', exc_info=True)
            published_model = ModelDeployDao.find_model_by_server_and_name(published_model.server,
                                                                           published_model.model)

        # 记录可用于训练的模型名称
        SftModelDao.insert_sft_model(published_model.model)

        # 更新训练任务状态
        logger.info('update sft job data')
        finetune.status = new_status
        finetune.model_id = published_model.id
        FinetuneDao.update_job(finetune)
        logger.info('export sft job success')
        return resp_200(data=finetune)

    @classmethod
    def cancel_publish_job(cls, job_id: UUID, user: Any) -> UnifiedResponseModel[Finetune]:
        # 查看job任务信息
        finetune = FinetuneDao.find_job(job_id)
        if not finetune:
            return NotFoundJobError.return_resp()
        new_status = FinetuneStatus.SUCCESS.value
        validate_ret = cls.validate_status(finetune, new_status)
        if validate_ret is not None:
            return validate_ret

        cls.delete_published_model(finetune, finetune.rt_endpoint)

        # 调用SFT-backend的API接口
        logger.info(f'start cancel export sft job: {job_id}, user: {user.get("user_name")}')
        sft_ret = SFTBackend.cancel_publish_job(host=parse_server_host(finetune.sft_endpoint), job_id=job_id.hex,
                                                model_name=finetune.model_name)
        if not sft_ret[0]:
            logger.error(f'cancel export sft job error: job_id: {job_id}, err: {sft_ret[1]}')
            return UnExportJobError.return_resp()
        SftModelDao.delete_sft_model(finetune.model_name)
        # 删除发布的模型信息
        logger.info(f'delete published model: {finetune.model_id}')
        ModelDeployDao.delete_model_by_id(finetune.model_id)
        logger.info('update finetune status')
        finetune.status = new_status
        finetune.model_id = 0
        FinetuneDao.update_job(finetune)
        logger.info('cancel export sft job success')
        return resp_200(data=finetune)

    @classmethod
    def get_server_by_cache(cls, server_id: int):
        # 先从内存获取
        cache_server = cls.ServerCache.get(server_id)
        if cache_server:
            return cls.ServerCache.get(server_id)
        # 再从数据库获取
        server = ServerDao.find_server(server_id)
        if server:
            cls.ServerCache.set(server_id, server)
            return server

    @classmethod
    def get_all_job(cls, req_data: FinetuneList) -> UnifiedResponseModel[List[Finetune]]:
        job_list, total = FinetuneDao.find_jobs(req_data)
        # 异步线程更新任务状态
        asyncio.get_event_loop().run_in_executor(sync_job_thread_pool, cls.sync_all_job_status, job_list)
        return resp_200(data={'data': job_list, 'total': total})

    @classmethod
    def sync_all_job_status(cls, job_list: List[Finetune]) -> None:
        # 异步线程更新批量任务的状态
        for finetune in job_list:
            cls.sync_job_status(finetune, finetune.sft_endpoint)

    @classmethod
    def get_job_info(cls, job_id: UUID) -> UnifiedResponseModel:
        """ 获取训练中任务的实时信息 """
        # 查看job任务信息
        finetune = FinetuneDao.find_job(job_id)
        if not finetune:
            return NotFoundJobError.return_resp()

        # 同步任务执行情况
        cls.sync_job_status(finetune, finetune.sft_endpoint)

        # 获取日志文件
        log_data = None
        res_data = list()
        if finetune.log_path:
            log_data = cls.get_job_log(finetune)
            res_data = cls.parse_log_data(log_data)

        return resp_200(data={
            'finetune': finetune,
            'log': log_data if finetune.status != FinetuneStatus.FAILED.value else finetune.reason,
            'loss_data': res_data,  # like [{"step": 10, "loss": 0.5}, {"step": 20, "loss": 0.3}]
            'report': finetune.report if finetune.report else None,
        })

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
            if elem_data['loss'] is None:
                continue
            sub_data['step'] = elem_data['current_steps']
            sub_data['loss'] = elem_data['loss']
            res_data.append(sub_data)
        return res_data

    @classmethod
    def sync_job_status(cls, finetune: Finetune, sft_endpoint: str) -> bool:
        """ 从SFT-backend服务同步任务状态 """
        if finetune.status != FinetuneStatus.TRAINING.value:
            return True
        logger.info(f'start sync job status: {finetune.id.hex}')

        sft_ret = SFTBackend.get_job_status(host=parse_server_host(sft_endpoint), job_id=finetune.id.hex)
        if not sft_ret[0]:
            logger.error(f'get sft job status error: job_id: {finetune.id.hex}, err: {sft_ret[1]}')
            return False
        if sft_ret[1]['status'] == SFTBackend.JOB_FINISHED:
            finetune.status = FinetuneStatus.SUCCESS.value
            FinetuneDao.change_status(finetune.id, finetune.status, FinetuneStatus.SUCCESS.value)
        elif sft_ret[1]['status'] == SFTBackend.JOB_FAILED:
            finetune.status = FinetuneStatus.FAILED.value
            finetune.reason = sft_ret[1]['reason']
            FinetuneDao.update_job(finetune)

        # 执行失败无需查询日志和报告
        if finetune.status == FinetuneStatus.FAILED.value:
            logger.info('sft job status failed, no need exec log and report')
            return False

        # 查询任务执行日志和报告
        logger.info('start query sft job log and report')
        sft_ret = SFTBackend.get_job_log(host=parse_server_host(sft_endpoint), job_id=finetune.id.hex)
        if not sft_ret[0]:
            logger.error(f'get sft job log error: job_id: {finetune.id.hex}, err: {sft_ret[1]}')
        log_data = sft_ret[1]['log_data'].encode('utf-8')
        # 上传日志文件到minio上
        log_path = cls.upload_job_log(finetune, io.BytesIO(log_data), len(log_data))
        finetune.log_path = log_path

        # 查询任务评估报告
        logger.info('start query sft job report')
        sft_ret = SFTBackend.get_job_metrics(host=parse_server_host(sft_endpoint), job_id=finetune.id.hex)
        if not sft_ret[0]:
            logger.error(f'get sft job report error: job_id: {finetune.id.hex}, err: {sft_ret[1]}')
        else:
            finetune.report = sft_ret[1]['report']

        # 更新日志和报告数据
        FinetuneDao.update_job(finetune)
        return True

    @classmethod
    def change_job_model_name(cls, req: FinetuneChangeModelName, user: any) -> UnifiedResponseModel[Finetune]:
        """ 修改训练任务的模型名称 """
        finetune = FinetuneDao.find_job(req.id)
        if not finetune:
            return NotFoundJobError.return_resp()

        # 校验模型名是否已存在
        if not cls.verify_job_model_name(req.model_name):
            return ModelNameExistsError.return_resp()

        # 修改已发布的模型名称
        if not cls.change_published_model_name(finetune, req.model_name):
            return ChangeModelNameError.return_resp()

        # 更新训练任务的model_name
        finetune.model_name = req.model_name
        FinetuneDao.update_job(finetune)

        return resp_200(data=finetune)

    @classmethod
    def change_published_model_name(cls, finetune: Finetune, model_name: str) -> bool:
        """ 修改训练任务的模型名称 """
        # 未发布的训练任务无需操作对应的model
        if finetune.status != FinetuneStatus.PUBLISHED.value:
            return True
        published_model = ModelDeployDao.find_model(finetune.model_id)
        if not published_model:
            logger.error(f'published model not found, job_id: {finetune.id.hex}, model_id: {finetune.model_id}')
            return False

        # 调用接口修改已发布模型的名称
        sft_ret = SFTBackend.change_model_name(parse_server_host(finetune.sft_endpoint), finetune.id.hex,
                                               published_model.model, model_name)
        if not sft_ret[0]:
            logger.error(f'change model name error: job_id: {finetune.id.hex}, err: {sft_ret[1]}')
            return False

        # 修改可预训练的模型名称
        SftModelDao.change_sft_model(published_model.model, model_name)

        # 更新已发布模型的model_name
        published_model.model = model_name
        ModelDeployDao.update_model(published_model)
        return True

    @classmethod
    def get_server_filters(cls) -> UnifiedResponseModel:
        """ 获取服务器过滤条件 """
        server_filters = FinetuneDao.get_server_filters()
        res = []
        for one in server_filters:
            res.append({
                'id': one,
                'server_name': one,
            })
        return resp_200(data=res)

    @classmethod
    def get_gpu_info(cls) -> UnifiedResponseModel:
        """ 获取GPU信息 """
        all_server = ServerDao.find_all_server()
        res = []
        for server in all_server:
            if not server.sft_endpoint:
                continue
            sft_ret = SFTBackend.get_gpu_info(parse_server_host(server.sft_endpoint))
            if not sft_ret[0]:
                logger.error(f'get gpu info error: server_id: {server.id}, err: {sft_ret[1]}')
                return GetGPUInfoError.return_resp()
            gpu_info = parse_gpus(sft_ret[1])
            for one in gpu_info:
                one['server'] = server.server
                res.append(one)
        return resp_200(data=res)
