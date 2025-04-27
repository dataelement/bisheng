from http import HTTPStatus
import dashscope
import json
import requests


class QwenSTT:
    def __init__(self, **kwargs):
        """
        初始化 STT 类
        :param api_key: 用于调用 API 的密钥
        """
        self.api_key = kwargs.get('api_key')
        self.model = kwargs.get('model')

    def transcribe(self, file_url):
        """
        执行语音转录
        :param file_urls: 要转录的音频文件 URL 列表
        :param language_hints: 语言提示列表，默认为中文
        :param model: 要使用的模型，默认为 paraformer - v2
        :return: 转录结果或错误信息
        """
        try:
            dashscope.api_key = self.api_key
            task_response = dashscope.audio.asr.Transcription.async_call(
                model=self.model,
                file_urls=[file_url],
                language_hints=["zh",'en'],
                api_key=self.api_key
            )
            transcribe_response = dashscope.audio.asr.Transcription.wait(task=task_response.output.task_id)
            if transcribe_response.status_code == HTTPStatus.OK:
                json_file = transcribe_response.output["results"][0]["transcription_url"]
                real_result = json.loads(requests.get(json_file).text)
                all_text = [r["text"] for r in real_result["transcripts"]]
                text = " ".join(all_text)
                return text
            else:
                raise Exception(f'transcription error! {transcribe_response.status_code}')
        except Exception as e:
            raise Exception(f"An error occurred during transcription {e}")
