from time import sleep

from fastapi import HTTPException, Request
import requests
from bisheng.database.models.gpts_tools import GptsToolsDao
import time
import json
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.hunyuan.v20230901 import hunyuan_client, models
from volcenginesdkarkruntime import Ark


class PackToolService:
    @classmethod
    def get_api_key(cls, request: Request):
        print(request.headers)
        authorization = request.headers.get('Authorization')
        if not authorization:
            raise HTTPException(status_code=401, detail="获取apikey失败，没有Authorization")
        if authorization.startswith('Basic '):
            return authorization.split('Basic ')[1]
        elif authorization.startswith('Bearer '):
            return authorization.split('Bearer ')[1]
        else:
            raise HTTPException(status_code=401, detail="Authorization格式不正确")

    @classmethod
    def albl_pack(cls, prompt: str, model: str, size: str, n: int, request: Request):
        """阿里百炼"""
        api_key = cls.get_api_key(request)
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
        headers = {
            'X-DashScope-Async': 'enable',
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            "model": model,
            "input": {
                "prompt": prompt
            },
            "parameters": {
                "size": size,
                "n": n
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            task_id = result.get('output', {}).get('task_id')
            if not task_id:
                raise HTTPException(status_code=500, detail="创建任务失败")
            sleep(5)
            return cls.albl_check_task_status(task_id, api_key)
        except requests.RequestException as e:
            raise HTTPException(status_code=500, detail=f"请求失败: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"失败: {str(e)}")

    @classmethod
    def albl_check_task_status(cls, task_id: str, api_key: str):
        """检查任务状态"""
        url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        attempt_count = 0
        while True:
            if attempt_count >= 20:
                raise HTTPException(status_code=500, detail="尝试次数过多，任务状态检查失败")
            attempt_count += 1
            try:
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                result = response.json()
                task_status = result.get('output', {}).get('task_status')

                if task_status == 'PENDING' or task_status == 'RUNNING':
                    time.sleep(3)
                    continue
                elif task_status == 'SUCCEEDED':
                    results = result.get('output', {}).get('results', [])
                    urls = [result.get('url') for result in results if result.get('url')]
                    return urls
                elif task_status == 'FAILED':
                    raise HTTPException(status_code=500, detail="任务执行失败")
                elif task_status == 'CANCELED':
                    raise HTTPException(status_code=200, detail="任务取消成功")
                else:
                    raise HTTPException(status_code=404, detail="任务不存在或状态未知")
            except requests.RequestException as e:
                raise HTTPException(status_code=500, detail=f"请求失败: {str(e)}")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"发生错误: {str(e)}")

    @classmethod
    def txhy_pack(cls, prompt: str, size: str, n: int, request: Request):
        api_key = cls.get_api_key(request)
        secret = api_key.split("##")
        if len(secret) != 2:
            raise HTTPException(status_code=500, detail="API Key 格式错误")
        try:
            cred = credential.Credential(secret[0], secret[1])
            httpProfile = HttpProfile()
            httpProfile.endpoint = "hunyuan.tencentcloudapi.com"

            clientProfile = ClientProfile()
            clientProfile.httpProfile = httpProfile
            client = hunyuan_client.HunyuanClient(cred, "ap-guangzhou", clientProfile)

            req = models.SubmitHunyuanImageJobRequest()
            params = {
                'Prompt': prompt,
                'Num': n,
                'Resolution': size,
                'LogoAdd': 0
            }
            req.from_json_string(json.dumps(params))

            resp = client.SubmitHunyuanImageJob(req)
            data_dict = json.loads(resp.to_json_string())
            task_id = data_dict.get("JobId")
            if not task_id:
                raise HTTPException(status_code=500, detail="创建任务失败")
            sleep(5)
            return cls.txhy_check_task_status(task_id, secret)
        except TencentCloudSDKException as err:
            raise HTTPException(status_code=500, detail=f"发生错误: {str(err)}")

    @classmethod
    def txhy_check_task_status(cls, task_id: str, secret: list[str]):
        """检查任务状态"""
        try:
            cred = credential.Credential(secret[0], secret[1])
            httpProfile = HttpProfile()
            httpProfile.endpoint = "hunyuan.tencentcloudapi.com"
            clientProfile = ClientProfile()
            clientProfile.httpProfile = httpProfile
            client = hunyuan_client.HunyuanClient(cred, "ap-guangzhou", clientProfile)

            req = models.QueryHunyuanImageJobRequest()
            params = {
                'JobId': task_id
            }
            req.from_json_string(json.dumps(params))

            attempt_count = 0
            while True:
                if attempt_count >= 20:
                    raise HTTPException(status_code=500, detail="尝试次数过多，任务状态检查失败")
                attempt_count += 1
                try:
                    response = client.QueryHunyuanImageJob(req)
                    data_dict = json.loads(response.to_json_string())
                    task_status = data_dict.get("JobStatusCode")
                    if task_status == "1" or task_status == "2":
                        time.sleep(3)
                        continue
                    elif task_status == '5':
                        return data_dict.get("ResultImage", [])
                    elif task_status == '4':
                        raise HTTPException(status_code=500, detail="处理失败")
                    else:
                        raise HTTPException(status_code=500, detail=f"位置状态：{task_status}")
                except requests.RequestException as e:
                    raise HTTPException(status_code=500, detail=f"请求失败: {str(e)}")
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"发生错误: {str(e)}")
        except TencentCloudSDKException as err:
            raise HTTPException(status_code=500, detail=f"调用腾讯SDK发生错误: {str(err)}")

    @classmethod
    def zjdb_pack(cls, prompt: str, model: str, size: str, request: Request):
        """字节豆包（火山引擎）"""
        api_key = cls.get_api_key(request)
        client = Ark(
            # 此为默认路径，您可根据业务所在地域进行配置
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            # 从环境变量中获取您的 API Key。此为默认方式，您可根据需要进行修改
            api_key=api_key,
        )
        imagesResponse = client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            response_format="url", # 返回图片样式，可选值：url、b64_json
            watermark=False # 是否生成水印
        )

        return [imagesResponse.data[0].url]