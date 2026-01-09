import json
from typing import Dict, List, Literal

from bisheng.core.external.http_client.http_client_manager import get_http_client


class SFTBackend:
    """ Packaging andSFT-BackendInteraction """

    # of fine-tuning training instructionsoptionsParameters Listing
    CMD_OPTIONS = ['train']

    # jobStatus Misi
    JOB_FINISHED = 'FINISHED'
    JOB_FAILED = 'FAILED'

    @classmethod
    async def handle_response(cls, res) -> (bool, str | None | Dict):
        content = await res.content.read()
        if res.status != 200:
            return False, content.decode('utf-8')
        result = json.loads(content)
        if result.get('status_code') != 200:
            return False, content.decode('utf-8')
        return True, result.get('data', None)

    @classmethod
    async def _base_request(cls, method: Literal['get', 'post'], *args, **kwargs) -> (bool, str | Dict):
        client = await get_http_client()
        client = await client.get_aiohttp_client()
        if method == 'get':
            res = await client.get(*args, **kwargs)
        else:
            res = await client.post(*args, **kwargs)
        return await cls.handle_response(res)

    @classmethod
    async def create_job(cls, host: str, job_id: str, params: Dict) -> (bool, str | Dict):
        """
        host RTof servicehost<g id="Bold">Address:</g>
        job_id is unique to the instructionid，UUIDFormat
        options Is InstructionoptionsParameters
        params Is InstructionalcommandParameter Parameter
        """
        uri = '/v2.1/sft/job'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post',
                                       f'{host}{url}',
                                       json={'uri': uri,
                                             'job_id': job_id,
                                             'options': cls.CMD_OPTIONS,
                                             'params': params})

    @classmethod
    async def cancel_job(cls, host: str, job_id: str) -> (bool, str | Dict):
        """ Cancel training task """
        uri = '/v2.1/sft/job/cancel'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}', json={'uri': uri, 'job_id': job_id})

    @classmethod
    async def delete_job(cls, host: str, job_id: str, model_name: str) -> (bool, str | Dict):
        """ Delete training task """
        uri = '/v2.1/sft/job/delete'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}',
                                       json={'uri': uri, 'job_id': job_id, 'model_name': model_name})

    @classmethod
    async def publish_job(cls, host: str, job_id: str, model_name: str) -> (bool, str | Dict):
        """ Publish Training Tasks From training path to formal path"""
        uri = '/v2.1/sft/job/publish'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}',
                                       json={'uri': uri, 'job_id': job_id, 'model_name': model_name})

    @classmethod
    async def cancel_publish_job(cls, host: str, job_id: str, model_name: str) -> (bool, str | Dict):
        """ Deactivate Training Task Published Model """
        uri = '/v2.1/sft/job/publish/cancel'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}',
                                       json={'uri': uri, 'job_id': job_id, 'model_name': model_name})

    @classmethod
    async def get_job_status(cls, host: str, job_id: str) -> (bool, str | Dict):
        """
         Get training task status
         Interface return format:
         {
            "status": "FINISHED",
            "reason": "Failure Reason"
         }
        """
        uri = '/v2.1/sft/job/status'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}', json={'uri': uri, 'job_id': job_id})

    @classmethod
    async def get_job_log(cls, host: str, job_id: str) -> (bool, str | Dict):
        """
        Get the training task log and use it temporarilydictFormat - Returns the contents of the
        TODO zgq Subsequent AdoptionhttpStandard File Transfer Format
        Data format returned by the interface
        {
            "log_data": Ref.bisheng-ftProduction Training Log File Contents
        }
        """
        uri = '/v2.1/sft/job/log'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}', json={'uri': uri, 'job_id': job_id})

    @classmethod
    async def get_job_metrics(cls, host: str, job_id: str) -> (bool, str | Dict):
        """
        Get training mission final report
        Interface return data format
        {
            "report": {}
        }
        """
        uri = '/v2.1/sft/job/metrics'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}', json={'uri': uri, 'job_id': job_id})

    @classmethod
    async def change_model_name(cls, host, job_id: str, old_model_name: str, model_name: str) -> (bool, str):
        """ Modify Model Name """
        uri = '/v2.1/sft/job/model_name'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}',
                                       json={'uri': uri, 'job_id': job_id, 'old_model_name': old_model_name,
                                             'model_name': model_name})

    @classmethod
    async def get_all_model(cls, host) -> (bool, List[str]):
        """ Get a list of all models """
        url = '/v2.1/sft/model'
        return await cls._base_request('get', f'{host}{url}')

    @classmethod
    async def get_gpu_info(cls, host) -> (bool, str):
        """ DapatkanGPUMessage """
        url = '/v2.1/sft/gpu'
        return await cls._base_request('get', f'{host}{url}')
