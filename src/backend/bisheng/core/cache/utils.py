import asyncio
import base64
import contextlib
import functools
import hashlib
import json
import os
import shutil
import tempfile
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Union, BinaryIO
from urllib.parse import unquote, urlparse
from uuid import uuid4

import aiofiles
import cchardet
import requests
from appdirs import user_cache_dir
from fastapi import UploadFile
from urllib3.util import parse_url

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
    """UsecchardetEncoding of the test file"""
    result = cchardet.detect(file_bytes)
    encoding = result['encoding']
    confidence = result['confidence']
    return encoding, confidence


def convert_encoding_cchardet(content: bytes, target_encoding='utf-8') -> BytesIO:
    """
    Convert file encoding to target_encoding using cchardet for detection.
    Args:
        content:
        target_encoding:

    Returns:
        BytesIO:

    """
    source_encoding, confidence = detect_encoding_cchardet(content)

    if confidence is None or confidence < 0.5 or source_encoding.lower() == target_encoding:
        return BytesIO(content)

    try:
        # decode using detected encoding
        text = content.decode(source_encoding)
    except (UnicodeDecodeError, LookupError):
        # If decoding fails, replace errors
        text = content.decode(target_encoding, errors='replace')

    # encode to target encoding
    return BytesIO(text.encode(target_encoding))


async def upload_file_to_minio(file: UploadFile, object_name, bucket_name: str) -> str:
    minio_client = await get_minio_storage()
    await minio_client.put_object(bucket_name=bucket_name, object_name=object_name, file=file.file)
    return await minio_client.get_share_link(object_name, bucket_name)


@create_cache_folder_async
async def save_file_to_folder(file: UploadFile, folder_name: str, file_name: str) -> str:
    """
    Save uploaded file tofolder_nameFolders
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
    async with aiofiles.open(file_path, 'wb') as out_file:
        while content := await file.read(8192):
            await out_file.write(content)

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
        folder_path.mkdir(parents=True, exist_ok=True)

    file_ext = file_name.split('.')[-1].lower()

    file_data_to_upload = None
    is_converted_text = False

    try:
        if file_ext in ('txt', 'md', 'csv'):
            raw_content = await file.read()

            file_data_to_upload = await asyncio.to_thread(
                convert_encoding_cchardet,
                content=raw_content,
                target_encoding='utf-8'
            )
            is_converted_text = True

        else:
            # For other file types, use the original uploaded file
            file_data_to_upload = file.file
            # Reset file pointer to the beginning
            file_data_to_upload.seek(0)
            is_converted_text = False

        await minio_client.put_object_tmp(object_name=file_name, file=file_data_to_upload)

    finally:
        if is_converted_text and file_data_to_upload:
            file_data_to_upload.close()

    file_path = await minio_client.get_share_link(file_name, bucket_name, clear_host=False)
    return file_path


@create_cache_folder
def save_download_file(file_input: Union[bytes, BinaryIO], folder_name: str, filename: str) -> str:
    """
    Synchronous I/O intensive tasks:
    Write data stream to a temporary file
    Simultaneously calculate SHA256
    Rename a file based on the hash
    """

    # Convert to stream objects
    if isinstance(file_input, bytes):
        src_stream = BytesIO(file_input)
    else:
        src_stream = file_input
        # Make sure the pointer is at the beginning
        if hasattr(src_stream, 'seek'):
            src_stream.seek(0)

    # Prepare a temporary file (write a temporary random filename first to avoid not being able to determine the filename before the hash calculation is finished).
    cache_path = Path(CACHE_DIR)
    folder_path = cache_path / folder_name

    # Create the folder if it doesn't exist
    if not folder_path.exists():
        folder_path.mkdir(exist_ok=True)

    temp_filename = f"tmp_{uuid4().hex}"
    temp_file_path = folder_path / temp_filename

    sha256_hash = hashlib.sha256()

    try:
        # Write to temporary file and calculate SHA256 simultaneously
        with open(temp_file_path, 'wb') as dst_file:
            chunk_size = 65536  # 64KB
            while True:
                chunk = src_stream.read(chunk_size)
                if not chunk:
                    break
                sha256_hash.update(chunk)
                dst_file.write(chunk)

        # calculate final hash
        file_hash = sha256_hash.hexdigest()

        # Logic for handling filename length limits
        safe_filename = filename
        if len(filename) > 60:
            safe_filename = filename[-60:]

        final_file_name = f'{file_hash}_{safe_filename}'
        final_file_path = folder_path / final_file_name

        # Rename (Move) Temporary File to Final Path
        # If the file already exists, decide whether to overwrite or skip it based on your needs. This example demonstrates overwriting.
        if final_file_path.exists():
            os.remove(temp_file_path)
            return str(final_file_path)

        shutil.move(str(temp_file_path), str(final_file_path))
        return str(final_file_path)

    except Exception as e:
        # Clean up temporary file in case of error
        if temp_file_path.exists():
            os.remove(temp_file_path)
        raise e
    finally:
        if isinstance(file_input, bytes):
            src_stream.close()


def file_download(file_path: str):
    """download file and return path"""

    # Try processing as a local file first (extracted URL Parameters)
    # If the system mounts a storage volume, remove ? The signature parameters behind it are read directly
    local_candidate = file_path.split('?')[0]
    if os.path.isfile(local_candidate):
        file_name = os.path.basename(local_candidate)
        # Compatible with legacy logic: handles what might be included in the filename md5 Prefix
        file_name = file_name.split('_', 1)[-1] if '_' in file_name else file_name
        return local_candidate, file_name

    # Legacy Logic: Check if it is standard URL (Bawa http/https)
    if _is_valid_url(file_path):
        minio_client = get_minio_storage_sync()
        minio_share_host = minio_client.get_minio_share_host()
        url_obj = urlparse(file_path)
        filename = unquote(url_obj.path.split('/')[-1])

        if file_path.startswith(minio_share_host):
            # download file from minio sdk
            bucket_name, object_name = url_obj.path.replace(minio_share_host, "", 1).lstrip("/").split('/', 1)
            object_name = unquote(object_name)
            file_content = minio_client.get_object_sync(bucket_name, object_name)
        else:
            # download file from http url
            r = requests.get(file_path, verify=False)
            if r.status_code != 200:
                raise ValueError('Check the url of your file; returned status code %s' % r.status_code)
            # OthersContent-Dispositionheader to find the filename
            content_disposition = r.headers.get('Content-Disposition')
            if content_disposition:
                filename = unquote(content_disposition).split('filename=')[-1].strip("\"'")
            file_content = r.content

        file_path = save_download_file(file_content, 'bisheng', filename)
        return file_path, filename

    # <g id="Bold">Medical Treatment:</g> MinIO Relative path (In / Starts with a signature parameter)
    # For Input: /bisheng/original/82324.docx?X-Amz-Algorithm=...
    # No in this case host, cannot be accessed _is_valid_url Branch
    elif file_path.startswith('/') and 'X-Amz-Algorithm' in file_path:
        try:
            minio_client = get_minio_storage_sync()

            # Use urlparse parsing, it automatically separates path And query
            url_obj = urlparse(file_path)
            # path similar to /bisheng/original/82324.docx
            # Remove the beginning /, and then split the first / Get bucket And object
            path_parts = url_obj.path.lstrip("/").split('/', 1)

            if len(path_parts) == 2:
                bucket_name, object_name = path_parts
                # Call Synchronized minio Method download
                object_name = unquote(object_name)
                file_content = minio_client.get_object_sync(bucket_name, object_name)

                filename = unquote(object_name.split('/')[-1])
                file_path = save_download_file(file_content, 'bisheng', filename)
                return file_path, filename
        except Exception as e:
            # If the parsing fails, print the log and let the program continue to throw down ValueError
            print(f"Error handling relative MinIO path: {e}")

    elif not os.path.isfile(file_path):
        raise ValueError('File path %s is not a valid file or url' % file_path)

    # This is the one that handles purely local file paths (the one with no parameters) and is usually handled by the topmost logic 1 Interception
    file_name = os.path.basename(file_path)
    file_name = file_name.split('_', 1)[-1] if '_' in file_name else file_name
    return file_path, file_name


async def async_file_download(file_path: str):
    """download file and return path"""

    # Try processing as a local file first (extracted URL Parameters)
    # If the system mounts the storage volume, this will solve the problem directly
    local_candidate = file_path.split('?')[0]
    if os.path.isfile(local_candidate):
        file_name = os.path.basename(local_candidate)
        # Is it included under processing?md5Logic of (Keep original logic)
        file_name = file_name.split('_', 1)[-1] if '_' in file_name else file_name
        return local_candidate, file_name

    # Check if it is standard URL
    if _is_valid_url(file_path):
        http_client = await get_http_client()
        minio_client = await get_minio_storage()
        minio_share_host = minio_client.get_minio_share_host()
        url_obj = parse_url(file_path)
        filename = unquote(url_obj.path.split('/')[-1])

        if file_path.startswith(minio_share_host):
            # download file from minio sdk
            bucket_name, object_name = url_obj.path.replace(minio_share_host, "", 1).lstrip("/").split('/', 1)
            object_name = unquote(object_name)
            file_content = await minio_client.get_object(bucket_name, object_name)
        else:
            r = await http_client.get(url=file_path, data_type="binary")
            if r.status_code != 200:
                raise ValueError('Check the url of your file; returned status code %s' % r.status_code)
            content_disposition = r.headers.get('Content-Disposition') if r.headers else None
            if content_disposition:
                filename = unquote(content_disposition).split('filename=')[-1].strip("\"'")
            file_content = r.body
        file_path = save_download_file(file_content, 'bisheng', filename)
        return file_path, filename

    # <g id="Bold">Medical Treatment:</g> MinIO Relative path (In / Starts with a signature parameter)
    # For Input: /bisheng/original/82324.docx?X-Amz-Algorithm=...
    elif file_path.startswith("/") and "X-Amz-Algorithm" in file_path:
        try:
            minio_client = await get_minio_storage()
            # Resolve Path /bucket/object_key
            url_obj = urlparse(file_path)
            # path turned into /bisheng/original/82324.docx, remove the opening / and split the first one /
            path_parts = url_obj.path.lstrip("/").split('/', 1)

            if len(path_parts) == 2:
                bucket_name, object_name = path_parts
                object_name = unquote(object_name)
                # Directly usable after finished products  leave the factory minio client Download without http Request
                file_content = await minio_client.get_object(bucket_name, object_name)

                filename = unquote(object_name.split('/')[-1])
                file_path = save_download_file(file_content, 'bisheng', filename)
                return file_path, filename
        except Exception as e:
            # If parsing or downloading fails, log or drop it below ValueError
            print(f"Error handling relative MinIO path: {e}")

    raise ValueError('File path %s is not a valid file or url' % file_path)


def _is_valid_url(url: str):
    """Check if the url is valid."""
    parsed = urlparse(url)
    return bool(parsed.netloc) and bool(parsed.scheme)
