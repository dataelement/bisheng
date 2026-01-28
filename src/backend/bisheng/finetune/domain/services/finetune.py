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
        """ Check request parameters, returningNoneIndicates check passed """
        # Individual Training Sets and Preset Training Sets Use at least one
        if not finetune.train_data and not finetune.preset_data:
            raise TrainDataNoneError()
        try:
            # Check Extra Parameter Values
            FinetuneExtraParams(**finetune.extra_params.copy())
        except ValidationError as e:
            logger.error(f'Finetune extra_params is invalid {e}')
            raise InvalidExtraParamsError()
        return None

    @classmethod
    def parse_command_params(cls, finetune: Finetune, base_model: ModelDeploy) -> Dict:
        """ Parse the request parameters and combine them into a training instructioncommandParameters """
        params = finetune.extra_params.copy()
        # Needs to be inSFT-backendThe service willmodel_nameAbsolute path to the model
        params['model_name_or_path'] = base_model.model
        params['model_template'] = finetune.root_model_name
        params['finetuning_type'] = finetune.method

        # Special treatedcpu_loadformat, because the transmission method is different --cpu_load means isTrue, no additional parameter values are required
        if params.get('cpu_load') == 'false':
            del params['cpu_load']
        elif params.get('cpu_load') == 'true':
            params['cpu_load'] = ''

        # Stitching training set parameters
        params['dataset'] = []
        params['each_max_samples'] = []
        cls.parse_command_train_file(finetune.train_data, params)
        cls.parse_command_train_file(finetune.preset_data, params)
        params['dataset'] = ','.join(params['dataset'])
        params['each_max_samples'] = ','.join(params['each_max_samples'])
        return params

    @classmethod
    def parse_command_train_file(cls, train_data: List[Dict], params: Dict):
        """ DapatkanminioA public link to the file onSFT-BackendDownload training files """
        if train_data is None:
            return
        minio_client = get_minio_storage_sync()
        for i in train_data:
            params['dataset'].append(minio_client.get_share_link_sync(i['url'], clear_host=False))
            params['each_max_samples'].append(str(i.get('num', 0)))

    @classmethod
    def validate_status(cls, finetune: Finetune, new_status: int) -> None:
        """ Verify that the state change is logical ReturnNoneIndicates success"""
        # Training can only To Training Success, Training Failure, Task Abort
        if finetune.status == FinetuneStatus.TRAINING.value:
            if new_status not in [FinetuneStatus.SUCCESS.value, FinetuneStatus.FAILED.value,
                                  FinetuneStatus.CANCEL.value]:
                raise JobStatusError.http_exception(msg='In training, it can only be changed to training success, training failure, task abort')
        # Training failed can only Becoming in training
        elif finetune.status == FinetuneStatus.FAILED.value:
            if new_status != FinetuneStatus.TRAINING.value:
                raise JobStatusError.http_exception(msg='A training failure can only turn into a training')
        # Task Aborted can only Becoming in training
        elif finetune.status == FinetuneStatus.CANCEL.value:
            if new_status != FinetuneStatus.TRAINING.value:
                raise JobStatusError.http_exception(msg='Task abort can only become in training')
        # Training Successful can only Change to Publish Complete
        elif finetune.status == FinetuneStatus.SUCCESS.value:
            if new_status != FinetuneStatus.PUBLISHED.value:
                raise JobStatusError.http_exception(msg='Training success can only change to release completion')
        # Publication complete can only Become Training Successful
        elif finetune.status == FinetuneStatus.PUBLISHED.value:
            if new_status != FinetuneStatus.SUCCESS.value:
                raise JobStatusError.http_exception(msg='Release completion can only be converted into training success')
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
        """ Correctionmodel_name Already exists? """
        if await ModelDeployDao.find_model_by_name(model_name):
            raise ModelNameExistsError()
        if await FinetuneDao.find_job_by_model_name(model_name):
            raise ModelNameExistsError()
        return True

    @classmethod
    async def create_job(cls, finetune: Finetune) -> Finetune:
        # Verify Extra Parameters
        _ = cls.validate_params(finetune)

        # CariSFTWhether the service exists
        server = await cls.get_sft_server(finetune.server)
        if not server:
            raise NoSftServerError()

        # Verify that the model name already exists
        await cls.verify_job_model_name(finetune.model_name)

        # Find out if the underlying model exists
        base_model = await ModelDeployDao.find_model(finetune.base_model)
        if not base_model:
            raise NotFoundModelError()
        root_model_name = base_model.model
        # Can find instructions for retraining based on trained and completed models
        if base_job := await FinetuneDao.find_job_by_model_name(base_model.model):
            root_model_name = base_job.root_model_name

        finetune.server_name = server.server
        finetune.rt_endpoint = server.endpoint
        finetune.sft_endpoint = server.sft_endpoint
        finetune.base_model_name = base_model.model
        finetune.root_model_name = root_model_name

        # RecallSFT-backendright of privacyAPIAdd New
        logger.info(f'start create sft job: {finetune.id}')
        # Required for stitching instructionscommandParameters
        command_params = cls.parse_command_params(finetune, base_model)
        sft_ret = await SFTBackend.create_job(host=parse_server_host(finetune.sft_endpoint),
                                              job_id=finetune.id, params=command_params)
        if not sft_ret[0]:
            logger.error(f'create sft job error: job_id: {finetune.id}, err: {sft_ret[1]}')
            raise CreateFinetuneError()
        # Insert into Database
        finetune = await FinetuneDao.insert_one(finetune)
        logger.info('create sft job success')
        return finetune

    @classmethod
    async def cancel_job(cls, job_id: str, user: UserPayload) -> Finetune:
        # ViewjobTask Information
        finetune = await FinetuneDao.find_job(job_id)
        if not finetune:
            raise NotFoundJobError()

        # Verify task status change
        new_status = FinetuneStatus.CANCEL.value
        cls.validate_status(finetune, new_status)

        # RecallSFT-backendright of privacyAPICancel Task
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
        # ViewjobTask Information
        finetune = await FinetuneDao.find_job(job_id)
        if not finetune:
            raise NotFoundJobError()

        model_name = await cls.delete_published_model(finetune)

        # Call the interface to delete the training task
        logger.info(f'start delete sft job: {job_id}, user: {user.user_name}')
        sft_ret = await SFTBackend.delete_job(host=parse_server_host(finetune.sft_endpoint), job_id=job_id,
                                              model_name=model_name)
        if not sft_ret[0]:
            logger.error(f'delete sft job error: job_id: {job_id}, err: {sft_ret[1]}')
            raise DeleteJobError()
        # Delete training task data
        logger.info('delete sft job data')
        # CleanedminioLog file on
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
         Offline the published model, delete the published model data, and return the published model name
         param finetune: Training Tasks
        """
        # Determine training task status
        if finetune.status != FinetuneStatus.PUBLISHED.value:
            return finetune.model_name
        # View published modelsID
        published_model = await ModelDeployDao.find_model(finetune.model_id)
        if not published_model:
            return finetune.model_name

        # Delete Published Model Data
        await ModelDeployDao.delete_model(published_model)
        logger.info(f'delete published model: {published_model.model}, id: {published_model.id}')
        return published_model.model

    @classmethod
    async def publish_job(cls, job_id: str, user: UserPayload) -> Finetune:
        # ViewjobTask Information
        finetune = await FinetuneDao.find_job(job_id)
        if not finetune:
            raise NotFoundJobError()
        new_status = FinetuneStatus.PUBLISHED.value
        cls.validate_status(finetune, new_status)

        # RecallSFT-backendright of privacyAPIInterfaces
        logger.info(f'start export sft job: {job_id}, user: {user.user_name}')
        sft_ret = await SFTBackend.publish_job(host=parse_server_host(finetune.sft_endpoint), job_id=job_id,
                                               model_name=finetune.model_name)
        if not sft_ret[0]:
            logger.error(f'export sft job error: job_id: {job_id}, err: {sft_ret[1]}')
            raise ExportJobError()
        # Create Published Model Data
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

        # Record the name of the model that can be used for training
        await SftModelDao.insert_sft_model(published_model.model)

        # Update training task status
        logger.info('update sft job data')
        finetune.status = new_status
        finetune.model_id = published_model.id
        await FinetuneDao.update_job(finetune)
        logger.info('export sft job success')
        return finetune

    @classmethod
    async def cancel_publish_job(cls, job_id: str, user: UserPayload) -> Finetune:
        # ViewjobTask Information
        finetune = await FinetuneDao.find_job(job_id)
        if not finetune:
            raise NotFoundJobError()
        new_status = FinetuneStatus.SUCCESS.value
        cls.validate_status(finetune, new_status)

        await cls.delete_published_model(finetune)

        # RecallSFT-backendright of privacyAPIInterfaces
        logger.info(f'start cancel export sft job: {job_id}, user: {user.user_name}')
        sft_ret = await SFTBackend.cancel_publish_job(host=parse_server_host(finetune.sft_endpoint), job_id=job_id,
                                                      model_name=finetune.model_name)
        if not sft_ret[0]:
            logger.error(f'cancel export sft job error: job_id: {job_id}, err: {sft_ret[1]}')
            raise UnExportJobError()
        await SftModelDao.delete_sft_model(finetune.model_name)
        # Delete published model information
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
        # Fetch from memory first
        cache_server = cls.ServerCache.get(server_id)
        if cache_server:
            return cls.ServerCache.get(server_id)
        # Retrieve from database
        server = await ServerDao.find_server(server_id)
        if server:
            cls.ServerCache.set(server_id, server)
        return server

    @classmethod
    async def get_all_job(cls, req_data: FinetuneList) -> (List[Finetune], int):
        job_list, total = await FinetuneDao.find_jobs(req_data)
        # Asynchronous thread update task status
        asyncio.create_task(cls.sync_all_job_status(job_list))
        return job_list, total

    @classmethod
    async def sync_all_job_status(cls, job_list: List[Finetune]) -> None:
        # Asynchronous threads update the status of bulk tasks
        for finetune in job_list:
            await cls.sync_job_status(finetune, finetune.sft_endpoint)

    @classmethod
    async def get_job_info(cls, job_id: str) -> Dict[str, Any]:
        """ Get real-time information on tasks in training """
        # ViewjobTask Information
        finetune = await FinetuneDao.find_job(job_id)
        if not finetune:
            raise NotFoundJobError()

        # Sync Task Execution
        await cls.sync_job_status(finetune, finetune.sft_endpoint)

        # Get log file
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
        """ FROMSFT-backendService Synchronization Task Status """
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

        # Execution failed without querying logs and reports
        if finetune.status == FinetuneStatus.FAILED.value:
            logger.info('sft job status failed, no need exec log and report')
            return False

        # Query task execution logs and reports
        logger.info('start query sft job log and report')
        sft_ret = await SFTBackend.get_job_log(host=parse_server_host(sft_endpoint), job_id=finetune.id)
        if not sft_ret[0]:
            logger.error(f'get sft job log error: job_id: {finetune.id}, err: {sft_ret[1]}')
        log_data = sft_ret[1]['log_data'].encode('utf-8')
        # Upload log file tominioUpward
        log_path = await cls.upload_job_log(finetune, io.BytesIO(log_data), len(log_data))
        finetune.log_path = log_path

        # Query Task Evaluation Report
        logger.info('start query sft job report')
        sft_ret = await SFTBackend.get_job_metrics(host=parse_server_host(sft_endpoint), job_id=finetune.id)
        if not sft_ret[0]:
            logger.error(f'get sft job report error: job_id: {finetune.id}, err: {sft_ret[1]}')
        else:
            finetune.report = sft_ret[1]['report']

        # Changelog and Report Data
        await FinetuneDao.update_job(finetune)
        return True

    @classmethod
    async def change_job_model_name(cls, req: FinetuneChangeModelName) -> Finetune:
        """ Modify the model name of the training task """
        finetune = await FinetuneDao.find_job(req.id)
        if not finetune:
            raise NotFoundJobError()

        # Verify that the model name already exists
        await cls.verify_job_model_name(req.model_name)

        # Modify Published Model Name
        if not await cls.change_published_model_name(finetune, req.model_name):
            raise ChangeModelNameError()

        # Update training task'smodel_name
        finetune.model_name = req.model_name
        await FinetuneDao.update_job(finetune)

        return finetune

    @classmethod
    async def change_published_model_name(cls, finetune: Finetune, model_name: str) -> bool:
        """ Modify the model name of the training task """
        # Unpublished training tasks do not require actionablemodel
        if finetune.status != FinetuneStatus.PUBLISHED.value:
            return True
        published_model = await ModelDeployDao.find_model(finetune.model_id)
        if not published_model:
            logger.error(f'published model not found, job_id: {finetune.id}, model_id: {finetune.model_id}')
            return False

        # Call the interface to modify the name of the published model
        sft_ret = await SFTBackend.change_model_name(parse_server_host(finetune.sft_endpoint), finetune.id,
                                                     published_model.model, model_name)
        if not sft_ret[0]:
            logger.error(f'change model name error: job_id: {finetune.id}, err: {sft_ret[1]}')
            return False

        # Modify pre-trained model name
        await SftModelDao.change_sft_model(published_model.model, model_name)

        # Updating the published model'smodel_name
        published_model.model = model_name
        await ModelDeployDao.update_model(published_model)
        return True

    @classmethod
    async def get_server_filters(cls) -> List[Dict[str, Any]]:
        """ DapatkanftServer Filter Criteria """
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
        """ DapatkanftList of all models under the service """
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
        """ DapatkanGPUMessage """
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
