"""11052 and 11059 carry the cap the path actually used, in mebibytes."""

import io
import struct
import zipfile
from types import SimpleNamespace

import pytest

from bisheng.common.errcode.linsight import SkillBundleTooLargeError, SkillFileTooLargeError
from bisheng.linsight.api.endpoints import skill as skill_endpoint
from bisheng.linsight.domain.services import github_skill_fetcher as fetcher_module
from bisheng.linsight.domain.services import skill_store
from bisheng.linsight.domain.services.github_skill_fetcher import GithubTarget, fetch_skill_files
from bisheng.linsight.domain.services.skill_service import SkillService
from bisheng.linsight.domain.services.skill_store import SKILL_MD

MB = 1024 * 1024


def _conf(monkeypatch, upload_mb: int, unpacked_mb: int) -> None:
    async def _aget(self):
        return SimpleNamespace(skill_upload_max_size_mb=upload_mb, skill_unpacked_max_size_mb=unpacked_mb)

    monkeypatch.setattr(type(skill_store.bisheng_settings), "aget_linsight_conf", _aget)


def _zip_declared_size(declared: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(SKILL_MD, b"x")
    raw = bytearray(buf.getvalue())
    struct.pack_into("<I", raw, raw.find(b"PK\x03\x04") + 22, declared)
    struct.pack_into("<I", raw, raw.rfind(b"PK\x01\x02") + 24, declared)
    return bytes(raw)


class _Upload:
    def __init__(self, data: bytes):
        self._data = data

    async def read(self):
        return self._data


class _FakeResponse:
    def __init__(self, json_data):
        self.status_code = 200
        self._json = json_data
        self.content = b""

    def json(self):
        return self._json


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        return _FakeResponse(self._payload)


async def test_admin_upload_reports_the_configured_upload_cap(monkeypatch):
    _conf(monkeypatch, 2, 9)
    with pytest.raises(SkillFileTooLargeError) as caught:
        await skill_endpoint._read_upload(_Upload(b"x" * (2 * MB + 1)))
    assert caught.value.to_dict()["data"]["limit_mb"] == 2


async def test_service_create_reports_both_configured_caps(monkeypatch):
    _conf(monkeypatch, 4, 6)
    service = object.__new__(SkillService)
    with pytest.raises(SkillFileTooLargeError) as upload_error:
        await service.create_from_upload(1, 7, "pdf.md", b"x" * (4 * MB + 1))
    assert upload_error.value.to_dict()["data"]["limit_mb"] == 4

    with pytest.raises(SkillBundleTooLargeError) as unpacked_error:
        await service.create_from_upload(1, 7, "pdf.zip", _zip_declared_size(6 * MB + 1))
    assert unpacked_error.value.to_dict()["data"]["limit_mb"] == 6


async def test_github_import_reports_the_configured_unpacked_cap(monkeypatch):
    _conf(monkeypatch, 2, 3)
    monkeypatch.setattr(
        fetcher_module.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _FakeClient(
            [{"name": "SKILL.md", "type": "file", "size": 3 * MB + 1, "download_url": "https://example.invalid/x"}]
        ),
    )
    with pytest.raises(SkillBundleTooLargeError) as caught:
        await fetch_skill_files(GithubTarget("o", "r", "main", ""))
    assert caught.value.to_dict()["data"]["limit_mb"] == 3
