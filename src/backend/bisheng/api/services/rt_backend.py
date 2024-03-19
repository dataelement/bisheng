import requests
from pydantic import BaseModel


class RTBackend(BaseModel):
    """ 封装和RT服务的交互 """

    @classmethod
    def handle_response(cls, res) -> (bool, str):
        if res.status_code != 200:
            return False, res.content.decode('utf-8')
        return True, 'success'

    @classmethod
    def unload_model(cls, host: str, model_name: str) -> (bool, str):
        """ 下线模型 """
        url = f'{host}/v2/repository/models/{model_name}/unload'
        res = requests.post(url)
        return cls.handle_response(res)
