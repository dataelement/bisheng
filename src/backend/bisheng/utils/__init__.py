import hashlib
import uuid

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
    return request.client.host
