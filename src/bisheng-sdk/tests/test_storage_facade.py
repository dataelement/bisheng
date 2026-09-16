"""storage 门面：同一套 API 两个后端、句柄每次重算（AC-20 / 21 / 22 / 23 / 25）。"""

from __future__ import annotations

import inspect
from pathlib import Path

import httpx
import pytest

from bisheng_sdk import storage
from bisheng_sdk.errors import AttachmentNotFoundError, InvalidAttachmentPathError
from tests.helpers import platform_mock as pm


def _fake_remote_store(mock_transport):
    """一个记性很好的假平台存储：足以跑完整条 put → stat → list → get → delete。"""
    objects: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path.split("/storage/", 1)[1]
        kind, _, raw = key.partition("/")
        from urllib.parse import unquote

        path = unquote(raw)
        if request.method == "PUT":
            objects[path] = request.content
            return httpx.Response(200, json=pm.storage_meta(path, len(request.content)))
        if request.method == "DELETE":
            if path not in objects:
                return httpx.Response(404, json=pm.manager_error_body("not_found", "missing"))
            objects.pop(path)
            return httpx.Response(200, json={})
        if kind == "meta":
            if path not in objects:
                return httpx.Response(404, json=pm.manager_error_body("not_found", "missing"))
            return httpx.Response(200, json=pm.storage_meta(path, len(objects[path])))
        if kind == "objects" and not path:
            prefix = request.url.params.get("prefix") or ""
            rows = [
                pm.storage_meta(name, len(blob)) for name, blob in sorted(objects.items()) if name.startswith(prefix)
            ]
            return httpx.Response(200, json={"objects": rows, "next_cursor": None})
        if path not in objects:
            return httpx.Response(404, json=pm.manager_error_body("not_found", "missing"))
        return httpx.Response(200, content=objects[path])

    return mock_transport(pm.RecordingTransport(handler))


@pytest.fixture(params=["local", "remote"])
def backend(request, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_transport) -> str:
    if request.param == "local":
        monkeypatch.setenv("BISHENG_APP_STORAGE_DIR", str(tmp_path / "attachments"))
    else:
        monkeypatch.setenv("BISHENG_APP_STORAGE_ENDPOINT", pm.STORAGE_ENDPOINT)
        monkeypatch.setenv("BISHENG_APP_STORAGE_TOKEN", pm.FAKE_STORAGE_TOKEN)
        _fake_remote_store(mock_transport)
    return request.param


def test_the_same_script_runs_on_both_backends(backend: str):
    meta = storage.put("报告/2026.pdf", b"hello world")
    assert (meta.path, meta.size) == ("报告/2026.pdf", 11)
    assert storage.stat("报告/2026.pdf").size == 11
    assert [row.path for row in storage.list("报告/")] == ["报告/2026.pdf"]
    assert storage.get("报告/2026.pdf") == b"hello world"
    storage.delete("报告/2026.pdf")
    with pytest.raises(AttachmentNotFoundError):
        storage.get("报告/2026.pdf")


def test_path_is_validated_before_any_io(backend: str):
    with pytest.raises(InvalidAttachmentPathError):
        storage.put("../escape", b"x")
    with pytest.raises(InvalidAttachmentPathError):
        storage.list("apps/")


def test_six_functions_and_six_async_twins_exist():
    """每个同步函数都要有异步孪生——少一个，用 FastAPI 的应用就只能在事件循环里阻塞。"""
    for name in ("put", "get", "open", "stat", "list", "delete"):
        assert callable(getattr(storage, name))
        twin = f"a{name}"
        assert inspect.iscoroutinefunction(getattr(storage, twin, None)), f"缺异步孪生 {twin}"


def test_handle_is_resolved_per_call_not_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    first = tmp_path / "one"
    monkeypatch.setenv("BISHENG_APP_STORAGE_DIR", str(first))
    storage.put("a.txt", b"1")

    second = tmp_path / "two"
    monkeypatch.setenv("BISHENG_APP_STORAGE_DIR", str(second))
    storage.put("b.txt", b"2")

    assert (first / "a.txt").is_file()
    assert (second / "b.txt").is_file()
    assert [row.path for row in storage.list()] == ["b.txt"]


async def test_async_roundtrip_on_the_local_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BISHENG_APP_STORAGE_DIR", str(tmp_path / "attachments"))
    await storage.aput("a.txt", b"hi")
    assert await storage.aget("a.txt") == b"hi"
    with await storage.aopen("a.txt") as handle:
        assert handle.read() == b"hi"
    assert [row.path for row in await storage.alist()] == ["a.txt"]
    await storage.adelete("a.txt")
    with pytest.raises(AttachmentNotFoundError):
        await storage.astat("a.txt")
