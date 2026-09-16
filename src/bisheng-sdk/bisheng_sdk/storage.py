"""当前应用的附件空间 —— 上传 / 下载 / 列举 / 删除，没有 bucket，没有对象键。

一行到位：

    from bisheng_sdk import storage

    meta = storage.put("报告/2026.pdf", data)
    blob = storage.get("报告/2026.pdf")

应用只见**应用内相对路径**与元信息。底层是哪个对象存储、桶叫什么、键怎么拼、
凭据是什么，一律不出现在这个模块的任何返回值与异常里（AC-21）。跨应用、路径穿越、
附件空间之外的写法一律明确拒绝，而不是静默映射到别处。

**同一套 API 两个后端**，按注入的句柄分辨（每次调用重算，`bisheng dev` 重启即
换）：

* ``BISHENG_APP_STORAGE_ENDPOINT``（+ ``_TOKEN``）→ 平台存储（托管期）
* ``BISHENG_APP_STORAGE_DIR`` → 项目本地附件目录（`bisheng dev` 期）
* **两个都有** → 报"句柄不唯一"。环境配错时宁可停下，也不猜一个后端——猜错的
  代价是附件默默落在另一个地方。

没有 ``clear()`` / ``delete_prefix()``：清空整个附件空间没有业务场景，误用即毁
数据。没有任何返回 URL 的函数：附件不进公共可读存储、也不提供绕过应用的直链，
要让用户下载就由应用自己吐流。
"""

from __future__ import annotations

import asyncio
from typing import IO, Any

from bisheng_sdk import _env, _paths, _storage_local, _storage_remote
from bisheng_sdk._attachment import AttachmentMeta
from bisheng_sdk.errors import StorageHandleMissingError

__all__ = (
    "AttachmentMeta",
    "adelete",
    "aget",
    "alist",
    "aput",
    "astat",
    "delete",
    "get",
    "list",
    "open",
    "put",
    "stat",
)

_BUILTIN_LIST = list


def _backend(*, is_async: bool = False):
    """解析句柄。每次调用重算、不缓存。"""
    endpoint = _env.storage_endpoint()
    directory = _env.storage_dir()

    if endpoint and directory:
        raise StorageHandleMissingError(
            "同时注入了平台存储句柄与本地附件目录句柄，无法判断附件该落在哪里",
            f"只保留其中一个：托管运行期是 {_env.ENV_STORAGE_ENDPOINT}，本地开发期是 {_env.ENV_STORAGE_DIR}",
        )
    if endpoint:
        token = _env.storage_token()
        if not token:
            raise StorageHandleMissingError(
                f"附件存储句柄不完整：有 {_env.ENV_STORAGE_ENDPOINT} 但没有 {_env.ENV_STORAGE_TOKEN}",
                "重新上线应用以取得完整句柄；不要手工改这两个平台保留环境变量",
            )
        if is_async:
            return _storage_remote.async_from_env(endpoint, token)
        return _storage_remote.from_env(endpoint, token)
    if directory:
        return _storage_local.LocalDirBackend(directory, max_bytes=_env.storage_max_file_bytes())
    raise StorageHandleMissingError()


# --- 同步面 ---------------------------------------------------------------


def put(path: str, data: Any, *, content_type: str | None = None) -> AttachmentMeta:
    """写入一个附件。超过单文件上限 → 明确错误，绝不截断写入。"""
    validated = _paths.validate(path)
    return _backend().put(validated, data, content_type)


def get(path: str) -> bytes:
    """整读一个附件。"""
    return _backend().get(_paths.validate(path))


def open(path: str) -> IO[bytes]:
    """流式读取一个附件（大文件用）。"""
    return _backend().open(_paths.validate(path))


def stat(path: str) -> AttachmentMeta:
    """只读元信息。"""
    return _backend().stat(_paths.validate(path))


def list(prefix: str = "", *, limit: int | None = None) -> _BUILTIN_LIST[AttachmentMeta]:
    """列举附件（按路径升序）。``limit`` 省略时取完所有页。"""
    return _backend().list(_paths.validate_prefix(prefix), limit)


def delete(path: str) -> None:
    """删除一个附件。附件不存在是错误，不是静默成功。"""
    _backend().delete(_paths.validate(path))


# --- 异步孪生 -------------------------------------------------------------
#
# 远端后端有真正的异步实现；本地目录后端用 `asyncio.to_thread` 包一层——磁盘 I/O
# 在事件循环里阻塞的时间虽短，但"本地能跑、线上卡住"是最难查的一类差异。


async def aput(path: str, data: Any, *, content_type: str | None = None) -> AttachmentMeta:
    validated = _paths.validate(path)
    backend = _backend(is_async=True)
    if isinstance(backend, _storage_remote.AsyncRemoteBackend):
        return await backend.aput(validated, data, content_type)
    return await asyncio.to_thread(backend.put, validated, data, content_type)


async def aget(path: str) -> bytes:
    validated = _paths.validate(path)
    backend = _backend(is_async=True)
    if isinstance(backend, _storage_remote.AsyncRemoteBackend):
        return await backend.aget(validated)
    return await asyncio.to_thread(backend.get, validated)


async def astat(path: str) -> AttachmentMeta:
    validated = _paths.validate(path)
    backend = _backend(is_async=True)
    if isinstance(backend, _storage_remote.AsyncRemoteBackend):
        return await backend.astat(validated)
    return await asyncio.to_thread(backend.stat, validated)


async def alist(prefix: str = "", *, limit: int | None = None) -> _BUILTIN_LIST[AttachmentMeta]:
    validated = _paths.validate_prefix(prefix)
    backend = _backend(is_async=True)
    if isinstance(backend, _storage_remote.AsyncRemoteBackend):
        return await backend.alist(validated, limit)
    return await asyncio.to_thread(backend.list, validated, limit)


async def adelete(path: str) -> None:
    validated = _paths.validate(path)
    backend = _backend(is_async=True)
    if isinstance(backend, _storage_remote.AsyncRemoteBackend):
        await backend.adelete(validated)
        return
    await asyncio.to_thread(backend.delete, validated)
