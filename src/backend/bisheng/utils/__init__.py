import hashlib
import io
import time
import uuid
from typing import BinaryIO

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


def calc_data_sha256(data: str | bytes | BinaryIO | None) -> str | None:
    """ calculate file md5 """
    if data is None:
        return None
    hasher = hashlib.sha256()
    if isinstance(data, (str, bytes)):
        hasher.update(data.encode() if isinstance(data, str) else data)
    elif isinstance(data, (io.BytesIO, io.IOBase, BinaryIO)) and data.readable():
        pos = data.tell()
        data.seek(0)

        chunk_size = 8192
        while True:
            chunk = data.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
        data.seek(pos)
    else:
        raise TypeError(
            "data must be str, bytes, or BinaryIO type",
        )
    return hasher.hexdigest()
