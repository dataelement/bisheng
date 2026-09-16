"""附件路径规则 —— runtime-manager `runtime_manager/storage.py::validate_key`
的逐条镜像（design D9）。

镜像而不是"差不多"：客户端先判一次是为了零请求就给出明确错误，服务端仍会再判
一次，两边规则一旦漂移，应用会看到"本地过、线上 400"。
`tests/test_contract_alignment.py` 读对方源码对账。

**拒绝而不是规范化**：``a/../b`` 会被拒，哪怕它规范化后就是 ``b``——写出
``a/../b`` 的应用几乎肯定想越界，诚实的回答是"不行"，而不是"给你 b"。
"""

from __future__ import annotations

import posixpath

from bisheng_sdk.errors import InvalidAttachmentPathError

#: S3 自己的上限；manager 先说一次。
MAX_KEY_BYTES = 1024

#: manager 保留的命名空间。哪怕是自己应用的 ``apps/…`` 前缀也拒——接受它等于
#: 告诉应用"这个命名空间是可寻址的"，它不是。
APPS_NAMESPACE = "apps/"


def validate(path: str) -> str:
    """合法则原样返回，否则抛 :class:`InvalidAttachmentPathError`。"""
    if not isinstance(path, str) or not path:
        raise InvalidAttachmentPathError(path=str(path), reason="路径为空")
    if len(path.encode("utf-8")) > MAX_KEY_BYTES:
        raise InvalidAttachmentPathError(path=path[:64] + "…", reason=f"超过 {MAX_KEY_BYTES} 字节")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in path):
        raise InvalidAttachmentPathError(path=repr(path), reason="含控制字符")
    if "\\" in path:
        raise InvalidAttachmentPathError(path=path, reason="含反斜杠")
    if path.startswith("/"):
        raise InvalidAttachmentPathError(path=path, reason="绝对路径")
    if path.endswith("/"):
        raise InvalidAttachmentPathError(path=path, reason="以 / 结尾")
    if any(segment in {"", ".", ".."} for segment in path.split("/")):
        raise InvalidAttachmentPathError(path=path, reason="含空段、`.` 或 `..`")
    if posixpath.normpath(path) != path:
        raise InvalidAttachmentPathError(path=path, reason="不是规范形")
    if path.startswith(APPS_NAMESPACE):
        raise InvalidAttachmentPathError(path=path, reason=f"`{APPS_NAMESPACE}` 是保留命名空间")
    return path


def validate_prefix(prefix: str) -> str:
    """列举用的前缀：空串、或一个可选以 ``/`` 结尾的路径。"""
    if prefix in ("", None):
        return ""
    if not isinstance(prefix, str):
        raise InvalidAttachmentPathError(path=str(prefix), reason="前缀不是字符串")
    if prefix.startswith(APPS_NAMESPACE):
        raise InvalidAttachmentPathError(path=prefix, reason=f"`{APPS_NAMESPACE}` 是保留命名空间")
    if prefix.endswith("/"):
        validate(prefix[:-1])
        return prefix
    validate(prefix)
    return prefix
