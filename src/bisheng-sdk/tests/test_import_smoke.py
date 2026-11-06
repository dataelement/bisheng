"""每个模块都能单独 import —— 一个循环 import 在应用容器里就是启动失败。"""

from __future__ import annotations

import importlib

import pytest

MODULES = [
    "bisheng_sdk",
    "bisheng_sdk.auth",
    "bisheng_sdk.retrieve",
    "bisheng_sdk.storage",
    "bisheng_sdk.errors",
    "bisheng_sdk._attachment",
    "bisheng_sdk._codes",
    "bisheng_sdk._compat",
    "bisheng_sdk._context",
    "bisheng_sdk._env",
    "bisheng_sdk._headers",
    "bisheng_sdk._http",
    "bisheng_sdk._paths",
    "bisheng_sdk._storage_local",
    "bisheng_sdk._storage_remote",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name: str):
    assert importlib.import_module(name) is not None


def test_import_does_no_io():
    """`import bisheng_sdk` 不打网络、不读盘——否则单测与探活都被拖下水。

    `no_network` 哨兵已经保证了前半句；这里断言导入后没有任何客户端被建出来。
    """
    from bisheng_sdk import _http

    importlib.reload(importlib.import_module("bisheng_sdk"))
    assert _http._clients == {}
    assert _http._aclients == {}


def test_httpx_is_available_with_both_faces():
    import httpx

    assert hasattr(httpx, "Client") and hasattr(httpx, "AsyncClient") and hasattr(httpx, "MockTransport")
