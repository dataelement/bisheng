from typing import Dict

import requests


class SFTBackend:
    """ 封装和SFT-Backend的交互 """

    # 微调训练指令的options参数列表
    CMD_OPTIONS = ['train']

    # job任务状态
    JOB_FINISHED = 'FINISHED'
    JOB_FAILED = 'FAILED'

    @classmethod
    def handle_response(cls, res) -> (bool, str | None | Dict):
        if res.status_code != 200 or res.json()['status_code'] != 200:
            return False, res.content.decode('utf-8')
        return True, res.json().get('data', None)

    @classmethod
    def create_job(cls, host: str, job_id: str, params: Dict) -> (bool, str | Dict):
        """
        host RT服务的host地址
        job_id 为指令唯一id，UUID格式
        options 为指令options参数
        params 为指令的command参数参数
        """
        url = f'{host}/v2.1/sft/job'
        res = requests.post(url, json={'job_id': job_id, 'options': cls.CMD_OPTIONS, 'params': params})
        return cls.handle_response(res)

    @classmethod
    def cancel_job(cls, host: str, job_id: str) -> (bool, str | Dict):
        """ 取消训练任务 """
        url = f'{host}/v2.1/sft/job/cancel'
        res = requests.post(url, json={'job_id': job_id})
        return cls.handle_response(res)

    @classmethod
    def delete_job(cls, host: str, job_id: str, model_name: str) -> (bool, str | Dict):
        """ 删除训练任务 """
        url = f'{host}/v2.1/sft/job/delete'
        res = requests.delete(url, json={'job_id': job_id, 'model_name': model_name})
        return cls.handle_response(res)

    @classmethod
    def publish_job(cls, host: str, job_id: str, model_name: str) -> (bool, str | Dict):
        """ 发布训练任务 从训练路径到处到正式路径"""
        url = f'{host}/v2.1/sft/job/publish'
        res = requests.post(url, json={'job_id': job_id, 'model_name': model_name})
        return cls.handle_response(res)

    @classmethod
    def get_job_status(cls, host: str, job_id: str) -> (bool, str | Dict):
        """
         获取训练任务状态
         接口返回格式：
         {
            "status": "FINISHED",
            "reason": "失败原因"
         }
        """
        url = f'{host}/v2.1/sft/job/status'
        res = requests.get(url, params={'job_id': job_id})
        return cls.handle_response(res)

    @classmethod
    def get_job_log(cls, host: str, job_id: str) -> (bool, str | Dict):
        """
        获取训练任务日志，暂时用dict格式返回文件内容
        TODO zgq 后续采用http标准文件传输格式
        接口返回的数据格式
        {
            "log_data": 参考bisheng-ft生产的训练日志文件内容
        }
        """
        url = f'{host}/v2.1/sft/job/log'
        res = requests.get(url, params={'job_id': job_id})
        return cls.handle_response(res)

    @classmethod
    def get_job_metrics(cls, host: str, job_id: str) -> (bool, str | Dict):
        """
        获取训练任务最终报告
        接口返回数据格式
        {
            "report": {}
        }
        """
        url = f'{host}/v2.1/sft/job/metrics'
        res = requests.get(url, params={'job_id': job_id})
        return cls.handle_response(res)

    @classmethod
    def change_model_name(cls, host, job_id: str, old_model_name: str, model_name: str) -> (bool, str):
        """ 修改模型名称 """
        url = f'{host}/v2.1/sft/job/model_name'
        res = requests.post(url, json={'job_id': job_id, 'old_model_name': old_model_name, 'model_name': model_name})
        return cls.handle_response(res)
