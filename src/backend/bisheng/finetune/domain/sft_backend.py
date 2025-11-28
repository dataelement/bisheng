import json
from typing import Dict, List, Literal

from bisheng.core.external.http_client.http_client_manager import get_http_client


class SFTBackend:
    """ 封装和SFT-Backend的交互 """

    # 微调训练指令的options参数列表
    CMD_OPTIONS = ['train']

    # job任务状态
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
        host RT服务的host地址
        job_id 为指令唯一id，UUID格式
        options 为指令options参数
        params 为指令的command参数参数
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
        """ 取消训练任务 """
        uri = '/v2.1/sft/job/cancel'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}', json={'uri': uri, 'job_id': job_id})

    @classmethod
    async def delete_job(cls, host: str, job_id: str, model_name: str) -> (bool, str | Dict):
        """ 删除训练任务 """
        uri = '/v2.1/sft/job/delete'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}',
                                       json={'uri': uri, 'job_id': job_id, 'model_name': model_name})

    @classmethod
    async def publish_job(cls, host: str, job_id: str, model_name: str) -> (bool, str | Dict):
        """ 发布训练任务 从训练路径到处到正式路径"""
        uri = '/v2.1/sft/job/publish'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}',
                                       json={'uri': uri, 'job_id': job_id, 'model_name': model_name})

    @classmethod
    async def cancel_publish_job(cls, host: str, job_id: str, model_name: str) -> (bool, str | Dict):
        """ 下架训练任务已发布的模型 """
        uri = '/v2.1/sft/job/publish/cancel'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}',
                                       json={'uri': uri, 'job_id': job_id, 'model_name': model_name})

    @classmethod
    async def get_job_status(cls, host: str, job_id: str) -> (bool, str | Dict):
        """
         获取训练任务状态
         接口返回格式：
         {
            "status": "FINISHED",
            "reason": "失败原因"
         }
        """
        uri = '/v2.1/sft/job/status'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}', json={'uri': uri, 'job_id': job_id})

    @classmethod
    async def get_job_log(cls, host: str, job_id: str) -> (bool, str | Dict):
        """
        获取训练任务日志，暂时用dict格式返回文件内容
        TODO zgq 后续采用http标准文件传输格式
        接口返回的数据格式
        {
            "log_data": 参考bisheng-ft生产的训练日志文件内容
        }
        """
        uri = '/v2.1/sft/job/log'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}', json={'uri': uri, 'job_id': job_id})

    @classmethod
    async def get_job_metrics(cls, host: str, job_id: str) -> (bool, str | Dict):
        """
        获取训练任务最终报告
        接口返回数据格式
        {
            "report": {}
        }
        """
        uri = '/v2.1/sft/job/metrics'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}', json={'uri': uri, 'job_id': job_id})

    @classmethod
    async def change_model_name(cls, host, job_id: str, old_model_name: str, model_name: str) -> (bool, str):
        """ 修改模型名称 """
        uri = '/v2.1/sft/job/model_name'
        url = '/v2.1/models/sft_elem/infer'
        return await cls._base_request('post', f'{host}{url}',
                                       json={'uri': uri, 'job_id': job_id, 'old_model_name': old_model_name,
                                             'model_name': model_name})

    @classmethod
    async def get_all_model(cls, host) -> (bool, List[str]):
        """ 获取所有的模型列表 """
        url = '/v2.1/sft/model'
        return await cls._base_request('get', f'{host}{url}')

    @classmethod
    async def get_gpu_info(cls, host) -> (bool, str):
        """ 获取GPU信息 """
        url = '/v2.1/sft/gpu'
        return await cls._base_request('get', f'{host}{url}')
