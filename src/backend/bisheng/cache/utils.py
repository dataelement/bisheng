import base64
import contextlib
import functools
import hashlib
import json
import os
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict
from urllib.parse import unquote, urlparse

import requests
from appdirs import user_cache_dir
from bisheng.settings import settings
from bisheng.utils.minio_client import MinioClient, tmp_bucket

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


@create_cache_folder
def save_uploaded_file(file, folder_name, file_name):
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
        folder_path.mkdir()

    # Create a hash of the file content
    sha256_hash = hashlib.sha256()
    # Reset the file cursor to the beginning of the file
    file.seek(0)
    # Iterate over the uploaded file in small chunks to conserve memory
    while chunk := file.read(8192):  # Read 8KB at a time (adjust as needed)
        sha256_hash.update(chunk)

    # Use the hex digest of the hash as the file name
    hex_dig = sha256_hash.hexdigest()
    md5_name = hex_dig

    # Reset the file cursor to the beginning of the file
    file.seek(0)

    # Save the file with the hash as its name
    if settings.get_knowledge().get('minio'):
        minio_client = MinioClient()
        # 存储oss
        file_byte = file.read()
        minio_client.upload_tmp(file_name, file_byte)
        file_path = minio_client.get_share_link(file_name, tmp_bucket)
    else:
        file_path = folder_path / f'{md5_name}_{file_name}'
        with open(file_path, 'wb') as new_file:
            while chunk := file.read(8192):
                new_file.write(chunk)

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
        folder_path.mkdir()

    # Create a hash of the file content
    sha256_hash = hashlib.sha256()
    # Reset the file cursor to the beginning of the file

    sha256_hash.update(file_byte)

    # Use the hex digest of the hash as the file name
    hex_dig = sha256_hash.hexdigest()
    md5_name = hex_dig
    file_type = filename.split('.')[-1]
    file_path = folder_path / f'{md5_name}.{file_type}'
    with open(file_path, 'wb') as new_file:
        new_file.write(file_byte)
    return str(file_path)


def file_download(file_path: str):
    """download file and return path"""
    if not os.path.isfile(file_path) and _is_valid_url(file_path):
        r = requests.get(file_path, verify=False)

        if r.status_code != 200:
            raise ValueError('Check the url of your file; returned status code %s' % r.status_code)
        # 检查Content-Disposition头来找出文件名
        content_disposition = r.headers.get('Content-Disposition')
        filename = ''
        if content_disposition:
            filename = unquote(content_disposition).split('filename=')[-1].strip("\"'")
        if not filename:
            filename = unquote(urlparse(file_path).path.split('/')[-1])
        file_path = save_download_file(r.content, 'bisheng', filename)
        return file_path, filename
    elif not os.path.isfile(file_path):
        raise ValueError('File path %s is not a valid file or url' % file_path)
    return file_path, file_path.split('_', 1)[1] if '_' in file_path else ''


def _is_valid_url(url: str):
    """Check if the url is valid."""
    parsed = urlparse(url)
    return bool(parsed.netloc) and bool(parsed.scheme)
