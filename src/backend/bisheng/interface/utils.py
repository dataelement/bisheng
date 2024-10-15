import base64
import datetime
import functools
import inspect
import json
import os
import re
from io import BytesIO

import yaml

from bisheng.cache.redis import redis_client
from bisheng.chat.config import ChatConfig
from bisheng.settings import settings
from bisheng.utils.logger import logger
from langchain.base_language import BaseLanguageModel
from PIL.Image import Image


def load_file_into_dict(file_path: str) -> dict:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f'File not found: {file_path}')

    # Files names are UUID, so we can't find the extension
    with open(file_path, 'r') as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            file.seek(0)
            data = yaml.safe_load(file)
        except ValueError as exc:
            raise ValueError('Invalid file type. Expected .json or .yaml.') from exc
    return data


def pil_to_base64(image: Image) -> str:
    buffered = BytesIO()
    image.save(buffered, format='PNG')
    img_str = base64.b64encode(buffered.getvalue())
    return img_str.decode('utf-8')


def try_setting_streaming_options(langchain_object, websocket):
    # If the LLM type is OpenAI or ChatOpenAI,
    # set streaming to True
    # First we need to find the LLM
    llm = None
    if hasattr(langchain_object, 'llm'):
        llm = langchain_object.llm
    elif hasattr(langchain_object, 'llm_chain') and hasattr(langchain_object.llm_chain, 'llm'):
        llm = langchain_object.llm_chain.llm

    if isinstance(llm, BaseLanguageModel):
        if hasattr(llm, 'streaming') and isinstance(llm.streaming, bool):
            llm.streaming = settings.get_from_db('llm_request').get(
                'stream') if 'stream' in settings.get_from_db(
                'llm_request') else ChatConfig.streaming
        elif hasattr(llm, 'stream') and isinstance(llm.stream, bool):
            llm.stream = settings.get_from_db('llm_request').get(
                'stream') if 'stream' in settings.get_from_db(
                'llm_request') else ChatConfig.streaming
    return langchain_object


def extract_input_variables_from_prompt(prompt: str) -> list[str]:
    """Extract input variables from prompt."""
    return re.findall(r'{(.*?)}', prompt)


def setup_llm_caching():
    """Setup LLM caching."""

    from bisheng.settings import settings

    try:
        set_langchain_cache(settings)
    except ImportError:
        logger.warning(f'Could not import {settings.cache}. ')
    except Exception as exc:
        logger.warning(f'Could not setup LLM caching. Error: {exc}')


# TODO Rename this here and in `setup_llm_caching`
def set_langchain_cache(settings):
    import langchain
    from bisheng.interface.importing.utils import import_class

    cache_type = os.getenv('bisheng_LANGCHAIN_CACHE')
    cache_class = import_class(f'langchain_community.cache.{cache_type or settings.cache}')

    logger.debug(f'Setting up LLM caching with {cache_class.__name__}')
    langchain.llm_cache = cache_class()
    logger.info(f'LLM caching setup with {cache_class.__name__}')


def bisheng_model_limit_check(self: 'BishengLLM | BishengEmbedding'):
    now = datetime.datetime.now().strftime("%Y-%m-%d")
    if self.server_info.limit_flag:
        # 开启了调用次数检查
        cache_key = f"model_limit:{now}:{self.server_info.id}"
        use_num = redis_client.incr(cache_key)
        if use_num > self.server_info.limit:
            raise Exception(f'额度已用完')


def wrapper_bisheng_model_limit_check_async(func):
    """
    调用次数检查的装饰器
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        bisheng_model_limit_check(args[0])
        return await func(*args, **kwargs)

    return wrapper


def wrapper_bisheng_model_limit_check(func):
    """
    调用次数检查的装饰器
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        bisheng_model_limit_check(args[0])
        return func(*args, **kwargs)

    return wrapper
