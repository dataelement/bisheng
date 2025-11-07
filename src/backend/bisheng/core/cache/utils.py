import base64
import contextlib
import functools
import hashlib
import json
import os
import tempfile
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from typing import Any, Dict
from urllib.parse import unquote, urlparse

import cchardet
import requests
from appdirs import user_cache_dir
from fastapi import UploadFile

from bisheng.core.external.http_client.http_client_manager import get_http_client
from bisheng.core.storage.minio.minio_manager import get_minio_storage, get_minio_storage_sync

CACHE: Dict[str, Any] = {}

CACHE_DIR = user_cache_dir('bisheng', 'bisheng')


def create_cache_folder(func):
    def wrapper(*args, **kwargs):
        # Get the destination folder
        cache_path = Path(CACHE_DIR) / PREFIX

        # Create the destination folder if it doesn't exist
        os.makedirs(cache_path, exist_ok=True)

        return func(*args, **kwargs)

    return wrapper


def create_cache_folder_async(func):
    async def wrapper(*args, **kwargs):
        # Get the destination folder
        cache_path = Path(CACHE_DIR) / PREFIX

        # Create the destination folder if it doesn't exist
        os.makedirs(cache_path, exist_ok=True)

        return await func(*args, **kwargs)

    return wrapper


def memoize_dict(maxsize=128):
    cache = OrderedDict()

    def decorator(func):

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            hashed = compute_dict_hash(args[0])
            key = (func.__name__, hashed, frozenset(kwargs.items()))
            if key not in cache:
                result = func(*args, **kwargs)
                cache[key] = result
                if len(cache) > maxsize:
                    cache.popitem(last=False)
            else:
                result = cache[key]
            return result

        def clear_cache():
            cache.clear()

        wrapper.clear_cache = clear_cache  # type: ignore
        wrapper.cache = cache  # type: ignore
        return wrapper

    return decorator


PREFIX = 'bisheng_cache'


@create_cache_folder
def clear_old_cache_files(max_cache_size: int = 3):
    cache_dir = Path(tempfile.gettempdir()) / PREFIX
    cache_files = list(cache_dir.glob('*.dill'))

    if len(cache_files) > max_cache_size:
        cache_files_sorted_by_mtime = sorted(cache_files,
                                             key=lambda x: x.stat().st_mtime,
                                             reverse=True)

        for cache_file in cache_files_sorted_by_mtime[max_cache_size:]:
            with contextlib.suppress(OSError):
                os.remove(cache_file)


def compute_dict_hash(graph_data):
    graph_data = filter_json(graph_data)

    cleaned_graph_json = json.dumps(graph_data, sort_keys=True)
    return hashlib.sha256(cleaned_graph_json.encode('utf-8')).hexdigest()


def filter_json(json_data):
    filtered_data = json_data.copy()

    # Remove 'viewport' and 'chatHistory' keys
    if 'viewport' in filtered_data:
        del filtered_data['viewport']
    if 'chatHistory' in filtered_data:
        del filtered_data['chatHistory']

    # Filter nodes
    if 'nodes' in filtered_data:
        for node in filtered_data['nodes']:
            if 'position' in node:
                del node['position']
            if 'positionAbsolute' in node:
                del node['positionAbsolute']
            if 'selected' in node:
                del node['selected']
            if 'dragging' in node:
                del node['dragging']

    return filtered_data


@create_cache_folder
def save_binary_file(content: str, file_name: str, accepted_types: list[str]) -> str:
    """
    Save a binary file to the specified folder.

    Args:
        content: The content of the file as a bytes object.
        file_name: The name of the file, including its extension.

    Returns:
        The path to the saved file.
    """
    if not any(file_name.endswith(suffix) for suffix in accepted_types):
        raise ValueError(f'File {file_name} is not accepted')

    # Get the destination folder
    cache_path = Path(CACHE_DIR) / PREFIX
    if not content:
        raise ValueError('Please, reload the file in the loader.')
    data = content.split(',')[1]
    decoded_bytes = base64.b64decode(data)

    # Create the full file path
    file_path = os.path.join(cache_path, file_name)

    # Save the binary content to the file
    with open(file_path, 'wb') as file:
        file.write(decoded_bytes)

    return file_path


def detect_encoding_cchardet(file_bytes: bytes, num_bytes=1024):
    """使用cchardet检测文件的编码"""
    result = cchardet.detect(file_bytes)
    encoding = result['encoding']
    confidence = result['confidence']
    return encoding, confidence


def convert_encoding_cchardet(file_io: BytesIO, target_encoding='utf-8'):
    """将文件转换为目标编码"""
    source_encoding, confidence = detect_encoding_cchardet(file_io.read())
    file_io.seek(0)
    if confidence is None or confidence < 0.5 or source_encoding.lower() == target_encoding:  # 检测不出来不做任何处理
        return file_io

    try:
        source_content = file_io.read().decode(source_encoding)
    except (UnicodeDecodeError, LookupError):
        file_io.seek(0)
        source_content = file_io.read().decode(target_encoding, errors='replace')
    output_file = BytesIO(source_content.encode(target_encoding))
    return output_file


async def upload_file_to_minio(file: UploadFile, object_name, bucket_name: str) -> str:
    minio_client = await get_minio_storage()
    file_byte = await file.read()
    await minio_client.put_object(bucket_name=bucket_name, object_name=object_name, file=file_byte)
    return minio_client.get_share_link(object_name, bucket_name)


@create_cache_folder_async
async def save_file_to_folder(file: UploadFile, folder_name: str, file_name: str) -> str:
    """
    保存上传的文件到folder_name文件夹
    :param file:
    :param folder_name:
    :param file_name:
    :return:
    """
    cache_path = Path(CACHE_DIR)
    folder_path = cache_path / folder_name

    # Create the folder if it doesn't exist
    os.makedirs(folder_path, exist_ok=True)

    # Save the file to the specified folder
    file_path = folder_path / file_name
    with open(file_path, 'wb') as f:
        content = await file.read()
        f.write(content)

    return str(file_path)


@create_cache_folder
async def save_uploaded_file(file: UploadFile, folder_name, file_name, bucket_name: str = None):
    """
    Save an uploaded file to the specified folder with a hash of its content as the file name.

    Args:
        file: The uploaded file object.
        folder_name: The name of the folder to save the file in.
        file_name: The name of the file, including its extension.
        bucket_name: The name of the bucket_name
    Returns:
        The path to the saved file.
    """

    minio_client = await get_minio_storage()

    if bucket_name is None:
        bucket_name = minio_client.tmp_bucket

    cache_path = Path(CACHE_DIR)
    folder_path = cache_path / folder_name

    # Create the folder if it doesn't exist
    if not folder_path.exists():
        folder_path.mkdir()

    # Reset the file cursor to the beginning of the file

    file_io = BytesIO(await file.read())
    # convert no utf-8 file to utf-8
    file_ext = file_name.split('.')[-1].lower()
    if file_ext in ('txt', 'md', 'csv'):
        file_io = convert_encoding_cchardet(file_io)

    await minio_client.put_object_tmp(object_name=file_name, file=file_io)
    file_path = minio_client.get_share_link(file_name, bucket_name)
    return file_path


@create_cache_folder
def save_download_file(file_byte, folder_name, filename):
    """
    Save an uploaded file to the specified folder with a hash of its content as the file name.

    Args:
        file: The uploaded file object.
        folder_name: The name of the folder to save the file in.

    Returns:
        The path to the saved file.
    """
    cache_path = Path(CACHE_DIR)
    folder_path = cache_path / folder_name

    # Create the folder if it doesn't exist
    if not folder_path.exists():
        folder_path.mkdir(exist_ok=True)

    # Create a hash of the file content
    sha256_hash = hashlib.sha256()
    # Reset the file cursor to the beginning of the file

    sha256_hash.update(file_byte)

    # Use the hex digest of the hash as the file name
    hex_dig = sha256_hash.hexdigest()
    md5_name = hex_dig
    file_path = folder_path / f'{md5_name}_{filename}'
    if len(filename) > 60:
        file_path = folder_path / f'{md5_name}_{filename[-60:]}'
    with open(file_path, 'wb') as new_file:
        new_file.write(file_byte)
    return str(file_path)


def file_download(file_path: str):
    """download file and return path"""
    if not os.path.isfile(file_path) and _is_valid_url(file_path):

        minio_client = get_minio_storage_sync()

        minio_share_host = minio_client.get_minio_share_host()
        filename = unquote(urlparse(file_path).path.split('/')[-1])

        if file_path.startswith(minio_share_host):
            # download file from minio sdk
            bucket_name, object_name = file_path.replace(minio_share_host, "", 1).lstrip("/").split('/', 1)
            file_content = minio_client.get_object_sync(bucket_name, object_name)
        else:
            # download file from http url
            r = requests.get(file_path, verify=False)
            if r.status_code != 200:
                raise ValueError('Check the url of your file; returned status code %s' % r.status_code)
            # 检查Content-Disposition头来找出文件名
            content_disposition = r.headers.get('Content-Disposition')
            filename = unquote(content_disposition).split('filename=')[-1].strip("\"'")
            file_content = r.content

        file_path = save_download_file(file_content, 'bisheng', filename)
        return file_path, filename
    elif not os.path.isfile(file_path):
        raise ValueError('File path %s is not a valid file or url' % file_path)
    file_name = os.path.basename(file_path)
    # 处理下是否包含了md5的逻辑
    file_name = file_name.split('_', 1)[-1] if '_' in file_name else file_name
    return file_path, file_name


async def async_file_download(file_path: str):
    """download file and return path"""
    if not os.path.isfile(file_path) and _is_valid_url(file_path):

        http_client = await get_http_client()

        minio_client = await get_minio_storage()

        file_path = file_path.replace(minio_client.minio_config.sharepoint, minio_client.minio_config.endpoint)

        r = await http_client.get(url=file_path, data_type="binary")

        if r.status_code != 200:
            raise ValueError('Check the url of your file; returned status code %s' % r.status_code)
        # 检查Content-Disposition头来找出文件名
        content_disposition = r.headers.get('Content-Disposition') if r.headers else None
        filename = ''
        if content_disposition:
            filename = unquote(content_disposition).split('filename=')[-1].strip("\"'")
        if not filename:
            filename = unquote(urlparse(file_path).path.split('/')[-1])
        file_path = save_download_file(r.body, 'bisheng', filename)
        return file_path, filename
    elif not os.path.isfile(file_path):
        raise ValueError('File path %s is not a valid file or url' % file_path)
    file_name = os.path.basename(file_path)
    # 处理下是否包含了md5的逻辑
    file_name = file_name.split('_', 1)[-1] if '_' in file_name else file_name
    return file_path, file_name


def _is_valid_url(url: str):
    """Check if the url is valid."""
    parsed = urlparse(url)
    return bool(parsed.netloc) and bool(parsed.scheme)
