"""Sandbox address save and dialog read model (F086)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.errcode.sandbox import SandboxEndpointInvalidError
from bisheng.core.config.settings import SandboxConf, encrypt_token
from bisheng.database.models.audit_log import EventType, ObjectType
from bisheng.tool.domain.services.sandbox_conf_service import SandboxConfService

_USER = SimpleNamespace(user_id=1, user_name="admin")


def _enc(token: str) -> str:
    raw = encrypt_token(token)
    return raw.decode() if isinstance(raw, bytes) else raw


class _Row:
    def __init__(self, value: str):
        self.value = value


@pytest.fixture
def saved(monkeypatch: pytest.MonkeyPatch) -> dict:
    holder = {
        "rows": {},
        "writes": [],
        "cache": [],
        "audits": [],
        "cache_error": None,
    }

    def get_config(key):
        value = holder["rows"].get(key.value)
        if value is None:
            return None
        return _Row(value)

    async def insert(key, value):
        holder["writes"].append((key, value))
        holder["rows"][key] = value
        return _Row(value)

    def write(payload):
        if holder["cache_error"]:
            raise holder["cache_error"]
        holder["cache"].append(payload)

    def audit(user, ip, note):
        holder["audits"].append((user, ip, note))

    monkeypatch.setattr("bisheng.tool.domain.services.sandbox_conf_service.ConfigDao.get_config", get_config)
    monkeypatch.setattr(
        "bisheng.tool.domain.services.sandbox_conf_service.ConfigDao.insert_or_update_config",
        insert,
    )
    monkeypatch.setattr(
        "bisheng.tool.domain.services.sandbox_conf_service.write_sandbox_endpoint_cache",
        write,
    )
    monkeypatch.setattr(
        "bisheng.tool.domain.services.sandbox_conf_service.AuditLogService.update_sandbox_conf",
        audit,
    )
    monkeypatch.setattr(
        "bisheng.tool.domain.services.sandbox_conf_service.settings.sandbox_conf",
        SandboxConf(endpoints=["http://dep:8080"], token="dep-token"),
    )
    return holder


async def test_save_stores_json_string_without_plaintext(saved):
    await SandboxConfService.save(["http://h:8080/"], "secret-token", _USER, "10.0.0.1")
    key, value = saved["writes"][0]
    assert key == "sandbox_endpoint"
    parsed = json.loads(value)
    assert "tenant_id" not in parsed
    assert parsed["endpoints"] == ["http://h:8080"]
    assert parsed["token_enc"] != "secret-token"
    assert "secret-token" not in value
    assert saved["cache"][0] == parsed
    assert isinstance(saved["cache"][0], dict)
    assert "secret-token" not in saved["cache"][0]["token_enc"]
    assert saved["audits"] == [(_USER, "10.0.0.1", "endpoints,已修改")]


@pytest.mark.parametrize(
    "endpoints",
    [
        ["ftp://h"],
        ["http://"],
        ["http://h:99999"],
        ["http://h:8080/", "http://h:8080"],
        ["http://h:8080"] * 33,
        [""],
        ["   "],
    ],
)
async def test_invalid_address_does_not_write(saved, endpoints):
    with pytest.raises(SandboxEndpointInvalidError):
        await SandboxConfService.save(endpoints, "secret-token", _USER, "10.0.0.1")
    assert saved["writes"] == []
    assert saved["cache"] == []
    assert "secret-token" not in json.dumps(saved["audits"])


async def test_mask_keeps_ciphertext_and_empty_clears_it(saved):
    stored = {"endpoints": ["http://h:8080"], "token_enc": _enc("kept-token")}
    saved["rows"]["sandbox_endpoint"] = json.dumps(stored)
    await SandboxConfService.save(["http://h:8080"], "********", _USER, "10.0.0.1")
    assert json.loads(saved["writes"][-1][1])["token_enc"] == stored["token_enc"]
    assert saved["audits"][-1][2] == ""
    await SandboxConfService.save(["http://h:8080"], "", _USER, "10.0.0.1")
    assert json.loads(saved["writes"][-1][1])["token_enc"] == ""
    assert saved["audits"][-1][2] == "已修改"
    assert "kept-token" not in saved["writes"][-1][1]


async def test_cache_write_failure_still_saves(saved):
    saved["cache_error"] = RuntimeError("redis")
    await SandboxConfService.save(["http://h:8080"], "secret-token", _USER, "10.0.0.1")
    assert saved["writes"]
    assert saved["audits"]
    assert saved["cache"] == []


async def test_save_does_not_call_http(saved, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("save must not open an HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    monkeypatch.setattr("bisheng.tool.domain.services.sandbox_conf_service.httpx.AsyncClient", boom)
    await SandboxConfService.save(["http://h:8080"], "secret-token", _USER, "10.0.0.1")


def test_get_empty_page_keeps_deployment_out_of_the_input(saved):
    view = SandboxConfService.get()
    assert view["endpoints"] == []
    assert view["token"] == ""
    assert view["address_source"] == "deployment"
    assert view["token_source"] == "deployment"
    assert view["deployment_address"] == "http://dep:8080"


@pytest.mark.parametrize("raw", ["{", "[]", "null", '{"endpoints": [1], "token_enc": ""}', "{}"])
def test_get_bad_structure_looks_like_no_page_config(saved, raw):
    saved["rows"]["sandbox_endpoint"] = raw
    view = SandboxConfService.get()
    assert view["endpoints"] == []
    assert view["token"] == ""
    assert view["address_source"] == "deployment"
    assert view["token_source"] == "deployment"


def test_sources_are_per_field(saved, monkeypatch):
    saved["rows"]["sandbox_endpoint"] = json.dumps({"endpoints": ["http://page:8080"], "token_enc": ""})
    view = SandboxConfService.get()
    assert view["endpoints"] == ["http://page:8080"]
    assert view["address_source"] == "page"
    assert view["token_source"] == "deployment"
    assert view["token"] == ""

    saved["rows"]["sandbox_endpoint"] = json.dumps({"endpoints": [], "token_enc": _enc("page-token")})
    view = SandboxConfService.get()
    assert view["endpoints"] == []
    assert view["token"] == "********"
    assert view["token_source"] == "page"
    assert view["address_source"] == "deployment"
    assert "page-token" not in json.dumps(view)

    monkeypatch.setattr(
        "bisheng.tool.domain.services.sandbox_conf_service.settings.sandbox_conf",
        SandboxConf(),
    )
    saved["rows"].clear()
    view = SandboxConfService.get()
    assert view["address_source"] == "default"
    assert view["token_source"] == "default"
    assert view["deployment_address"] == ""


def test_audit_uses_empty_groups_and_sandbox_object(monkeypatch):
    captured = {}

    def fake_system(user, ip, group_ids, event_type, object_type, object_id, object_name, note=""):
        captured.update(
            group_ids=group_ids,
            event_type=event_type,
            object_type=object_type,
            object_id=object_id,
            object_name=object_name,
            note=note,
        )

    monkeypatch.setattr(
        AuditLogService, "_system_log", classmethod(lambda cls, *args, **kwargs: fake_system(*args, **kwargs))
    )
    AuditLogService.update_sandbox_conf(_USER, "10.0.0.1", "endpoints")
    assert captured["group_ids"] == []
    assert captured["event_type"] == EventType.UPDATE_SANDBOX_CONF
    assert captured["object_type"] == ObjectType.TOOL
    assert captured["object_id"] == "sandbox_endpoint"
    assert captured["object_name"] == "sandbox_endpoint"
    assert captured["note"] == "endpoints"
    assert "secret" not in captured["note"]
