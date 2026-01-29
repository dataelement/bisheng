import hashlib
import io
import time
import uuid
from typing import BinaryIO, Union, IO

from fastapi import Request, WebSocket


def generate_uuid() -> str:
    """ generate uuid4 string """
    return uuid.uuid4().hex


def md5_hash(original_string: str):
    """ generate md5 hash string """
    md5 = hashlib.md5()
    md5.update(original_string.encode('utf-8'))
    return md5.hexdigest()


def get_request_ip(request: Request | WebSocket) -> str:
    """ get client real ip address """
    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    ip = request.headers.get('X-Real-IP')
    if ip:
        return ip
    return request.client.host


def generate_knowledge_index_name() -> str:
    """ generate knowledge index name """
    return f"col_{int(time.time())}_{generate_uuid()[:8]}"


def calc_data_sha256(data: Union[str, bytes, IO[bytes], None]) -> Union[str, None]:
    """
    calculate sha256 hash of data
    :param data: str, bytes, or a file-like object (with read() method)
    :return: sha256 hex digest string or None
    """
    if data is None:
        return None

    hasher = hashlib.sha256()

    # Handle str and bytes directly
    if isinstance(data, (str, bytes)):
        if isinstance(data, str):
            data = data.encode('utf-8')
        hasher.update(data)
        return hasher.hexdigest()

    if hasattr(data, 'read'):
        # Assume it's a file-like object
        try:
            current_pos = data.tell()
        except Exception:
            current_pos = 0

        data.seek(0)

        chunk_size = 65536  # 64KB per chunk
        while True:
            chunk = data.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)

        # Reset the file pointer to its original position
        data.seek(current_pos)
        return hasher.hexdigest()

    return None
