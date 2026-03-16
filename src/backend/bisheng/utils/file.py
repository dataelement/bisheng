import hashlib
import io
import os
from io import BytesIO
from typing import Union, BinaryIO, Tuple
from urllib.parse import urlparse, unquote

import requests
from appdirs import user_cache_dir
from requests import Response
from urllib3 import BaseHTTPResponse

from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.utils import generate_uuid

CACHE_DIR = user_cache_dir('bisheng', 'bisheng')

FILE_CACHE_DIR = os.path.join(CACHE_DIR, 'downloaded')
os.makedirs(FILE_CACHE_DIR, exist_ok=True)


def _is_valid_url(url: str):
    """Check if the url is valid."""
    parsed = urlparse(url)
    return bool(parsed.netloc) and bool(parsed.scheme)


def save_download_file(file_input: Union[bytes, BinaryIO, BaseHTTPResponse, Response], filename: str,
                       root_dir: str = None,
                       calc_sha256: bool = False) -> Tuple[str, str]:
    """
    Synchronous I/O intensive tasks:
    Write data stream to a temporary file
    Simultaneously calculate SHA256
    Rename a file based on the hash
    """
    if root_dir is None:
        root_dir = FILE_CACHE_DIR

    # Convert to stream objects
    if isinstance(file_input, bytes):
        src_stream = BytesIO(file_input)
    else:
        src_stream = file_input
        # Make sure the pointer is at the beginning
        try:
            if hasattr(src_stream, 'seek'):
                src_stream.seek(0)
        # http response objects may not support seek, so we can ignore UnsupportedOperation exceptions
        except io.UnsupportedOperation:
            pass

    file_name, file_extension = os.path.splitext(filename)

    # create temp folder
    temp_file_path = os.path.join(root_dir, generate_uuid())
    os.makedirs(os.path.dirname(temp_file_path), exist_ok=True)

    # Logic for handling filename length limits,
    safe_filename = filename
    if len(filename) > 60:
        safe_filename = filename[-60:]

    temp_file_path = os.path.join(temp_file_path, f"{safe_filename}{file_extension}")

    sha256_hash = hashlib.sha256() if calc_sha256 else None

    def calc_tmp_sha256(tmp_content: bytes):
        if sha256_hash:
            sha256_hash.update(tmp_content)

    try:
        # Write to temporary file and calculate SHA256 simultaneously
        with open(temp_file_path, 'wb') as dst_file:
            chunk_size = 65536  # 64KB
            # minio response
            if hasattr(src_stream, 'stream'):
                for one in src_stream.stream(chunk_size):
                    calc_tmp_sha256(one)
                    dst_file.write(one)
            # requests response
            elif hasattr(src_stream, 'iter_content'):
                for one in src_stream.iter_content(chunk_size):
                    calc_tmp_sha256(one)
                    dst_file.write(one)
            # other file-like objects
            else:
                while True:
                    one = src_stream.read(chunk_size)
                    if not one:
                        break
                    calc_tmp_sha256(one)
                    dst_file.write(one)

        if sha256_hash:
            return temp_file_path, sha256_hash.hexdigest()
        return temp_file_path, ""

    except Exception as e:
        # Clean up temporary file in case of error
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise e
    finally:
        if isinstance(file_input, bytes):
            src_stream.close()


def download_minio_file(bucket_name: str = None, object_name: str = None, *, root_dir: str = None,
                        calc_sha256: bool = False) -> Tuple[str, str]:
    """ download file from minio
        Returns:
             1、local file path
             2、file_sha_256 if calc_sha256 is True else ""
    """
    if object_name is None:
        raise ValueError('object_name are required')
    minio_client = get_minio_storage_sync()
    file_response = None
    try:
        file_response = minio_client.download_object_sync(bucket_name, object_name)
        return save_download_file(file_response, object_name, root_dir=root_dir, calc_sha256=calc_sha256)
    finally:
        if file_response:
            file_response.release_conn()
            file_response.close()


def download_network_file(file_url: str, *, root_dir: str = None, calc_sha256: bool = False) -> Tuple[str, str]:
    # download file from http url
    r = None
    try:
        r = requests.get(file_url, stream=True)
        if r.status_code != 200:
            raise ValueError('Check the url of your file; returned status code %s' % r.status_code)
        # Content-Disposition header to find the filename
        content_disposition = r.headers.get('Content-Disposition')
        if content_disposition:
            filename = unquote(content_disposition).split('filename=')[-1].strip("\"'")
        else:
            filename = unquote(urlparse(file_url).path.split('/')[-1])
        return save_download_file(r, filename=filename, root_dir=root_dir, calc_sha256=calc_sha256)
    finally:
        if r:
            r.close()


def download_file(file_url: str, *, root_dir: str = None, calc_sha256: bool = False) -> Tuple[str, str]:
    if _is_valid_url(file_url):
        minio_client = get_minio_storage_sync()
        minio_share_host = minio_client.get_minio_share_host()
        if file_url.startswith(minio_share_host):
            url_obj = urlparse(file_url)
            # path turned into /bisheng/original/82324.docx, remove the opening / and split the first one /
            path_parts = url_obj.path.lstrip("/").split('/', 1)
            bucket_name, object_name = path_parts
            object_name = unquote(object_name)
            return download_minio_file(bucket_name, object_name, root_dir=root_dir, calc_sha256=calc_sha256)

        # download from network, we can use requests to download the file
        return download_network_file(file_url, root_dir=root_dir, calc_sha256=calc_sha256)
    # <g id="Bold">Medical Treatment:</g> MinIO Relative path (In / Starts with a signature parameter)
    # For Input: /bisheng/original/82324.docx?X-Amz-Algorithm=...
    # No in this case host, cannot be accessed _is_valid_url Branch
    elif file_url.startswith('/') and 'X-Amz-Algorithm' in file_url:
        url_obj = urlparse(file_url)
        # path turned into /bisheng/original/82324.docx?xxx, remove the opening / and split the first one /
        path_parts = url_obj.path.lstrip("/").split('/', 1)
        if len(path_parts) != 2:
            raise ValueError(f"Invalid file path: {file_url}")
        bucket_name, object_name = path_parts
        object_name = unquote(object_name)
        return download_minio_file(bucket_name, object_name, root_dir=root_dir, calc_sha256=calc_sha256)
    else:
        raise ValueError(f'File path {file_url} is not a valid file or url')
