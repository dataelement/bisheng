import uuid


def generate_uuid() -> str:
    """
    生成uuid的字符串
    """
    return uuid.uuid4().hex
