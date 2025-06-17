import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends, Body, UploadFile

from bisheng.api.services.llm import LLMService
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.utils import tts_text_md5_hash, md5_hash
from bisheng.api.v1.schemas import (UnifiedResponseModel, resp_200, resp_500)
from bisheng.interface.stts.custom import BishengSTT
from bisheng.interface.ttss.custom import BishengTTS
from bisheng.cache.redis import redis_client
from fastapi import (APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, Request,
                     UploadFile)
from bisheng.cache.utils import save_uploaded_file

router = APIRouter(prefix='/model_fun', dependencies=[Depends(get_login_user)])


@router.post('/tts', response_model=UnifiedResponseModel)
async def tts(*,
              text: str = Body(description='需要转成语音的文字'),
              model_id: int = Body(description='用户使用的模型id', default=0)):
    try:

        if not model_id:
            model_id = LLMService.get_default_tts_model_id()
        if not text:
            return resp_500(message=f'text 不能为空')
        text_md5 = tts_text_md5_hash(text)
        key = f"ttslock_{text_md5}_{model_id}"
        if not redis_client.setNx(key, 1, 30):
            return resp_500(message=f'转化中，请稍后再试')
        url = BishengTTS(model_id=model_id).synthesize_and_upload(text)
        redis_client.delete(key)
        return resp_200(data={"url": url})
    except Exception as e:
        return resp_500(message=f'{str(e)}')


@router.post('/stt', response_model=UnifiedResponseModel)
async def stt(*,
              url: str = Body(description='需要转成文字的语音'),
              model_id: int = Body(description='用户使用的模型id', default=0)):
    try:

        if not model_id:
            model_id = LLMService.get_default_stt_model_id()
        if not url:
            return resp_500(message=f'url 不能为空')
        url_md5 = md5_hash(url)
        value_key = f"stt_{url_md5}_{model_id}_text"
        lock_key = f"sttlock_{url_md5}_{model_id}"
        # 使用海象运算符在 if 语句中赋值并判断
        if cached_text := redis_client.get(value_key):
            return resp_200(data={"text": cached_text})
        if not redis_client.setNx(lock_key, 1, 30):
            return resp_500(message=f'转化中，请稍后再试')
        text = BishengSTT(model_id=model_id).transcribe(url)
        redis_client.set(value_key, text, expiration=3600)
        redis_client.delete(lock_key)
        return resp_200(data={"text": text})
    except Exception as e:
        return resp_500(message=f'{str(e)}')


@router.post('/upload_and_stt', response_model=UnifiedResponseModel)
async def upload_file(*, file: UploadFile = File(...)):
    try:
        file_name = file.filename
        # 缓存本地
        url = save_uploaded_file(file.file, 'bisheng', file_name)
        if not isinstance(url, str):
            url = str(url)
        model_id = LLMService.get_default_stt_model_id()
        url_md5 = md5_hash(url)
        value_key = f"stt_{url_md5}_{model_id}_text"
        lock_key = f"sttlock_{url_md5}_{model_id}"
        # 使用海象运算符在 if 语句中赋值并判断
        if cached_text := redis_client.get(value_key):
            return resp_200(data={"text": cached_text})
        if not redis_client.setNx(lock_key, 1, 30):
            return resp_500(message=f'转化中，请稍后再试')
        text = BishengSTT(model_id=model_id).transcribe(url)
        redis_client.set(value_key, text, expiration=3600)
        redis_client.delete(lock_key)
        return resp_200(data={"text": text})
    except Exception as e:
        return resp_500(message=f'{str(e)}')
