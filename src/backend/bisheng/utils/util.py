import asyncio
import functools
import hashlib
import io
import json
import logging
import time
import zipfile
from functools import wraps
from typing import Union, List, Tuple
from urllib.parse import urlparse

from docstring_parser import parse
from sqlalchemy import JSON, TypeDecorator  # type: ignore

logger = logging.getLogger(__name__)

class DMJSON(TypeDecorator):
    impl = JSON  # 底层依赖达梦的 JSON 类型
    def process_bind_param(self, value, dialect):
        # 写入数据库：字典转 JSON 字符串
        if value is None:
            return None
        return json.dumps(value)
    def process_result_value(self, value, dialect):
        # 读取数据库：JSON 字符串转字典
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {}
        return value
    
def sync_to_async(func):
    """
    Decorator to convert a sync function to an async function.
    """

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return async_wrapper


def run_async(coro, loop=None):
    """
    Run asynchronous functions
    :param coro:
    :param loop:
    :return:
    """
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
            return loop.run_until_complete(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)

    return loop.run_until_complete(coro)


def get_cache_key(flow_id: str, chat_id: str, vertex_id: str = None):
    return f'{flow_id}_{chat_id}_{vertex_id}'


def _is_valid_url(url: str) -> bool:
    """Check if the url is valid."""
    parsed = urlparse(url)
    return bool(parsed.netloc) and bool(parsed.scheme)


# Retry decorator Asynchronous
def retry_async(num_retries=3, delay=0.5, return_exceptions=False):
    def wrapper(func):
        async def wrapped(*args, **kwargs):
            for i in range(num_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    logger.info(
                        f"Retrying {func.__name__} in {delay} seconds... Attempt {i + 1} of {num_retries}... error: {e}")
                    if i == num_retries - 1:
                        if return_exceptions:
                            # Return Exception Parameters will bee.argsSplit into tuples
                            return e.args if len(e.args) > 1 else e.args[0]
                        logger.error(f"Failed to execute {func.__name__} after {num_retries} retries")
                        raise e
                    await asyncio.sleep(delay)
            return None

        return wrapped

    return wrapper


# Retry decorator
def retry_sync(num_retries=3, delay=0.5, return_exceptions=False):
    def wrapper(func):
        def wrapped(*args, **kwargs):
            for i in range(num_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    logger.info(
                        f"Retrying {func.__name__} in {delay} seconds... Attempt {i + 1} of {num_retries}... error: {e}")
                    if i == num_retries - 1:
                        if return_exceptions:
                            # Return Exception Parameters will bee.argsSplit into tuples
                            return e.args if len(e.args) > 1 else e.args[0]
                        logger.error(f"Failed to execute {func.__name__} after {num_retries} retries")
                        raise e
                    time.sleep(delay)
            return None

        return wrapped

    return wrapper


def calculate_md5(file: Union[str, bytes]):
    """Calculating the Document's MD5 .
    Returns:
        str: of the document MD5 .
    """
    md5_hash = hashlib.md5()

    if isinstance(file, bytes):
        md5_hash.update(file)
        return md5_hash.hexdigest()

    else:
        # Reading Files in Binary Form
        with open(file, "rb") as f:
            # Read files by block to avoid large files taking up too much memory
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)

        return md5_hash.hexdigest()


async def async_calculate_md5(file: Union[str, bytes]):
    """of the asynchronous computation document MD5 .
    Returns:
        str: of the document MD5 .
    """
    import aiofiles

    md5_hash = hashlib.md5()

    if isinstance(file, bytes):
        md5_hash.update(file)
        return md5_hash.hexdigest()

    else:
        # Read files asynchronously in binary form
        async with aiofiles.open(file, "rb") as f:
            # Read files asynchronously by block to avoid large files taking up too much memory
            while True:
                chunk = await f.read(4096)
                if not chunk:
                    break
                md5_hash.update(chunk)

        return md5_hash.hexdigest()


# Read all files in the directory
def read_files_in_directory(path: str):
    """
    Reads all files in the directory and returns a list of filenames.
    Args:
        path (str): Directory Path
    Returns:
        list: List of filenames.
    """
    import os

    if not os.path.exists(path):
        logger.error(f"Path {path} does not exist.")
        return []

    files = []
    for root, _, filenames in os.walk(path):
        for filename in filenames:
            files.append(os.path.join(root, filename))
    return files


def sync_func_to_async(func, executor=None):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        loop = asyncio.get_running_loop()
        bound_func = functools.partial(func, *args, **kwargs)
        return await loop.run_in_executor(executor, bound_func)

    return wrapper


def bytes_to_zip(
        files: List[Tuple[str, bytes]],
        compress_level: int = 6
) -> bytes:
    """
    Package byte stream data intoZIPfiles, back toZIPByte Stream for Files

    Parameters:
        files: Contains(The file name, Byte Stream)List of tuples
        compress_level: compression level(0-9)，0Indicates no compression,9Represents the highest compression rate

    Return:
        Date GeneratedZIPFile Byte Stream
    """
    try:
        # Verify compression level
        if not 0 <= compress_level <= 9:
            raise ValueError("The compression level must be0to9Between")

        # Create in-memory byte streams for storageZIPDATA
        zip_buffer = io.BytesIO()

        # BuatZIPFile and add byte stream data
        with zipfile.ZipFile(
                zip_buffer,
                'w',
                zipfile.ZIP_DEFLATED,
                compresslevel=compress_level
        ) as zipf:
            for filename, data in files:
                # Enter your messageZIPAdd byte stream data to the file
                zipf.writestr(filename, data)
                print(f"Was added: {filename} (size: {len(data) / 1024:.2f} KB)")

        # will beZIPData is positioned to the starting position and returns a byte stream
        zip_buffer.seek(0)
        zip_data = zip_buffer.getvalue()

        logger.debug(f"\nZIPFile created successfully, total size: {len(zip_data) / 1024:.2f} KB")
        return zip_data

    except Exception as e:
        logger.error(f"Packaging process error: {str(e)}")
        raise e
