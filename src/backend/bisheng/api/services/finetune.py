from typing import Any, Dict

from bisheng.api.errcode.finetune import (CancelJobError, CreateFinetuneError, DeleteJobError,
                                          ExportJobError, JobStatusError, NotFoundJobError,
                                          TrainDataNoneError)
from bisheng.api.errcode.model_deploy import NotFoundModelError
from bisheng.api.errcode.server import NotFoundServerError
from bisheng.api.services.rt_backend import RTBackend
from bisheng.api.services.sft_backend import SFTBackend
from bisheng.api.utils import parse_server_host
from bisheng.api.v1.schemas import UnifiedResponseModel
from bisheng.database.models.finetune import Finetune, FinetuneCreate, FinetuneDao, FinetuneStatus
from bisheng.database.models.model_deploy import ModelDeploy, ModelDeployDao
from bisheng.database.models.server import ServerDao
from bisheng.utils.logger import logger
from pydantic import BaseModel


class FinetuneService(BaseModel):

    @classmethod
    def validate_params(cls, finetune_create: FinetuneCreate) -> UnifiedResponseModel | None:
        """ 检查请求参数，返回None表示校验通过 """
        # 个人训练集和预置训练集 最少使用一个
        if not finetune_create.train_data and not finetune_create.preset_data:
            return TrainDataNoneError.return_resp()
        return None

    @classmethod
    def parse_command_params(cls, finetune: Finetune, base_model: ModelDeploy) -> Dict:
        """ 解析请求参数，组合成训练指令的command参数 """
        params = finetune.extra_params.copy()
        # 需要在SFT-backend服务将model_name转为模型所在的绝对路径
        params['model_name_or_path'] = base_model.model
        params['finetuning_type'] = finetune.method

        # 拼接训练集参数
        params['dataset'] = []
        params['max_samples'] = []
        if finetune.train_data is not None:
            for i in finetune.train_data:
                params['dataset'].append(i['url'])
                params['max_samples'].append(i['num'])
        if finetune.preset_data is not None:
            for i in finetune.preset_data:
                params['dataset'].append(i['url'])
                params['max_samples'].append(i['num'])
        params['dataset'] = ','.join(params['dataset'])
        params['max_samples'] = ','.join(params['max_samples'])
        return params

    @classmethod
    def validate_status(cls, finetune: Finetune, new_status: int) -> UnifiedResponseModel | None:
        """ 校验状态变更是否符合逻辑 返回None表示成功"""
        # 训练中 只能 变为训练成功、训练失败、任务中止
        if finetune.status == FinetuneStatus.TRAINING.value:
            if new_status not in [FinetuneStatus.SUCCESS.value, FinetuneStatus.FAILED.value,
                                  FinetuneStatus.CANCEL.value]:
                return JobStatusError.return_resp('训练中只能变为训练成功、训练失败、任务中止')
        # 训练失败 只能 变为训练中
        elif finetune.status == FinetuneStatus.FAILED.value:
            if new_status != FinetuneStatus.TRAINING.value:
                return JobStatusError.return_resp('训练失败只能变为训练中')
        # 任务中止 只能 变为训练中
        elif finetune.status == FinetuneStatus.CANCEL.value:
            if new_status != FinetuneStatus.TRAINING.value:
                return JobStatusError.return_resp('任务中止只能变为训练中')
        # 训练成功 只能 变为发布完成
        elif finetune.status == FinetuneStatus.SUCCESS.value:
            if new_status != FinetuneStatus.PUBLISHED.value:
                return JobStatusError.return_resp('训练成功只能变为发布完成')
        # 发布完成 只能 变为训练成功
        elif finetune.status == FinetuneStatus.PUBLISHED.value:
            if new_status != FinetuneStatus.SUCCESS.value:
                return JobStatusError.return_resp('发布完成只能变为训练成功')
        return None

    @classmethod
    def create_finetune(cls, finetune_create: FinetuneCreate, user: Any) -> UnifiedResponseModel[Finetune]:
        # 校验额外参数
        validate_ret = cls.validate_params(finetune_create)
        if validate_ret is not None:
            return validate_ret

        # 查找RT服务是否存在
        server = ServerDao.find_server(finetune_create.server)
        if not server:
            return NotFoundServerError.return_resp()

        # 查找基础模型是否存在
        base_model = ModelDeployDao.find_model(finetune_create.base_model)
        if not base_model:
            return NotFoundModelError.return_resp()

        # 插入到数据库内
        finetune_create.user_id = user.get('user_id')
        finetune_create.user_name = user.get('user_name')
        finetune = FinetuneDao.insert_one(Finetune(**finetune_create.dict()))

        # 调用SFT-backend的API新建任务
        logger.info(f'start create sft job: {finetune.id.hex}')
        # 拼接指令所需的command参数
        command_params = cls.parse_command_params(finetune, base_model)
        sft_ret = SFTBackend.create_job(host=parse_server_host(server.endpoint),
                                        job_id=finetune.id.hex, params=command_params)
        if not sft_ret[0]:
            logger.error(f'create sft job error: job_id: {finetune.id.hex}, err: {sft_ret[1]}')
            return CreateFinetuneError.return_resp(None)
        logger.info('create sft job success')
        return UnifiedResponseModel(status_code=200, msg='success', data=Finetune)

    @classmethod
    def cancel_finetune(cls, job_id: str, user: Any) -> UnifiedResponseModel[Finetune]:
        # 查看job任务信息
        finetune = FinetuneDao.find_job(job_id)
        if not finetune:
            return NotFoundJobError.return_resp()

        # 校验任务状态变化
        new_status = FinetuneStatus.CANCEL.value
        validate_ret = cls.validate_status(finetune, new_status)
        if validate_ret is not None:
            return validate_ret

        # 查找RT服务是否存在
        server = ServerDao.find_server(finetune.server)
        if not server:
            return NotFoundServerError.return_resp()

        # 调用SFT-backend的API取消任务
        logger.info(f'start cancel job_id: {job_id}, user: {user.get("user_name")}')
        sft_ret = SFTBackend.cancel_job(host=parse_server_host(server.endpoint), job_id=job_id)
        if not sft_ret[0]:
            logger.error(f'cancel sft job error: job_id: {job_id}, err: {sft_ret[1]}')
            return CancelJobError.return_resp(None)
        logger.info('change sft job status')
        FinetuneDao.change_status(job_id, finetune.status, FinetuneStatus.CANCEL.value)
        finetune.status = new_status
        logger.info('cancel sft job success')
        return UnifiedResponseModel(status_code=200, msg='success', data=Finetune)

    @classmethod
    def delete_finetune(cls, job_id: str, user: Any) -> UnifiedResponseModel[Finetune]:
        # 查看job任务信息
        finetune = FinetuneDao.find_job(job_id)
        if not finetune:
            return NotFoundJobError.return_resp()
        # 查找RT服务是否存在
        server = ServerDao.find_server(finetune.server)
        if not server:
            return NotFoundServerError.return_resp()

        model_name = cls.delete_published_model(finetune, server.endpoint)

        # 调用接口删除训练任务
        logger.info(f'start delete sft job: {job_id}, user: {user.get("user_name")}')
        sft_ret = SFTBackend.delete_job(host=parse_server_host(server.endpoint), job_id=job_id, model_name=model_name)
        if not sft_ret[0]:
            logger.error(f'delete sft job error: job_id: {job_id}, err: {sft_ret[1]}')
            return DeleteJobError.return_resp(None)
        # 删除训练任务数据
        logger.info('delete sft job data')
        FinetuneDao.delete_job(finetune)
        logger.info('delete sft job success')

    @classmethod
    def delete_published_model(cls, finetune: Finetune, server_endpoint: str) -> str | None:
        """ 下线已发布模型，删除已发布模型数据，返回已发布模型名称 """
        # 判断训练任务状态
        if finetune.status != FinetuneStatus.PUBLISHED.value:
            return None
        # 查看已发布模型ID
        published_model = ModelDeployDao.find_model(finetune.model_id)
        if not published_model:
            return None
        if published_model.status == '已上线':
            # 调用RT接口下线模型
            ret = RTBackend.unload_model(parse_server_host(server_endpoint), published_model.model)
            if ret[0] is False:
                logger.error(f'unload published model error: {published_model.model}, err: {ret[1]}')
            else:
                logger.info(f'unload published model: {published_model.model}, resp: {ret}')
        # 删除已发布模型数据
        ModelDeployDao.delete_model(published_model)
        logger.info(f'delete published model: {published_model.model}, id: {published_model.id}')
        return published_model.model

    @classmethod
    def export_job(cls, job_id: str, user: Any) -> UnifiedResponseModel[Finetune]:
        # 查看job任务信息
        finetune = FinetuneDao.find_job(job_id)
        if not finetune:
            return NotFoundJobError.return_resp()
        new_status = FinetuneStatus.PUBLISHED.value
        validate_ret = cls.validate_status(finetune, new_status)
        if validate_ret is not None:
            return validate_ret

        # 查找RT服务是否存在
        server = ServerDao.find_server(finetune.server)
        if not server:
            return NotFoundServerError.return_resp()

        # 调用SFT-backend的API接口
        logger.info(f'start export sft job: {job_id}, user: {user.get("user_name")}')
        sft_ret = SFTBackend.export_job(host=parse_server_host(server.endpoint), job_id=job_id,
                                        model_name=finetune.model_name)
        if not sft_ret[0]:
            logger.error(f'export sft job error: job_id: {job_id}, err: {sft_ret[1]}')
            return ExportJobError.return_resp(None)
        # 创建已发布模型数据
        logger.info('create published model')
        published_model = ModelDeploy(model=finetune.model_name,
                                      server=str(server.id),
                                      endpoint=server.endpoint)
        published_model = ModelDeployDao.insert_one(published_model)
        # 更新训练任务状态
        logger.info('update sft job data')
        finetune.status = new_status
        finetune.model_id = published_model.id
        FinetuneDao.update_job(finetune)
        logger.info('export sft job success')
        return UnifiedResponseModel(status_code=200, msg='success', data=finetune)
