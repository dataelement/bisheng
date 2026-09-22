# ruff: noqa: RUF002
"""知识统计共用文档身份；独立文件与文档使用不同命名空间。"""

from typing import Any


def document_identity(file_id: int, document_id: Any = None) -> str:
    if int(file_id) <= 0 or (document_id is not None and int(document_id) <= 0):
        raise ValueError("知识统计身份必须为正整数")
    return f"document:{int(document_id)}" if document_id is not None else f"file:{int(file_id)}"
