"""Configuration readiness is fail-closed; model execution stays best-effort."""

import base64
import json

import pytest

from bisheng.dsh.audit_runtime import ModelAuditRuntime
from bisheng.dsh.config import DshSettings
from test.dsh.test_model_audit_flow import ADMIN, BASE, LOCAL_ADMIN, call, fixture


def bind_production_modes(harness, monkeypatch, active_id):
    import bisheng.dsh.audit_admin_runtime as composition

    monkeypatch.setattr(composition, "authorize_admin", harness.authorize)
    monkeypatch.setattr(composition, "repository_scope", harness.scope)
    settings = DshSettings(audit_active_key_id=active_id)
    modes = composition.build_audit_administration(settings).modes
    harness.admin.modes = modes
    return settings


@pytest.mark.parametrize(
    "key_mapping,active_id",
    [
        (None, "active"),
        ("{}", "active"),
        ("invalid-json", "active"),
        ('{"active":"AA=="}', "active"),
        ('{"active":"not-base64"}', "active"),
        (json.dumps({"other": base64.b64encode(bytes(32)).decode()}), "active"),
        (json.dumps({"active": base64.b64encode(bytes(32)).decode()}), None),
    ],
)
async def test_missing_or_invalid_keys_reject_content_without_changing_mode(monkeypatch, key_mapping, active_id):
    if key_mapping is None:
        monkeypatch.delenv("BS_DSH_MODEL_AUDIT_KEYS", raising=False)
    else:
        monkeypatch.setenv("BS_DSH_MODEL_AUDIT_KEYS", key_mapping)
    async with fixture("OFF") as (harness, client, _objects):
        bind_production_modes(harness, monkeypatch, active_id)
        snapshot = (await client.get(BASE + "/settings", headers=ADMIN, params={"tenant_id": 2})).json()["data"]
        assert snapshot == {"mode": "OFF", "version": 1, "content_available": False}
        rejected = await client.put(
            BASE + "/settings/2",
            headers=ADMIN,
            json={"operation_id": "readiness-enable", "expected_version": 1, "mode": "CONTENT"},
        )
        assert rejected.json()["status_code"] == 26135
        assert (await client.get(BASE + "/settings", headers=ADMIN, params={"tenant_id": 2})).json()["data"] == snapshot
        for version, mode in ((1, "METADATA"), (2, "OFF")):
            saved = await client.put(
                BASE + "/settings/2",
                headers=ADMIN,
                json={"operation_id": mode, "expected_version": version, "mode": mode},
            )
            assert saved.json()["data"] == {"mode": mode, "version": version + 1, "content_available": False}


async def test_save_rechecks_keys_after_read_and_rejected_operation_can_be_retried(monkeypatch):
    encoded = base64.b64encode(bytes(range(32))).decode()
    valid = json.dumps({"active": encoded})
    monkeypatch.setenv("BS_DSH_MODEL_AUDIT_KEYS", valid)
    async with fixture("OFF") as (harness, client, _objects):
        bind_production_modes(harness, monkeypatch, "active")
        ready = (await client.get(BASE + "/settings", headers=ADMIN, params={"tenant_id": 2})).json()["data"]
        assert ready["content_available"] is True
        monkeypatch.setenv("BS_DSH_MODEL_AUDIT_KEYS", "{}")
        command = {"operation_id": "readiness-retry", "expected_version": 1, "mode": "CONTENT"}
        rejected = await client.put(BASE + "/settings/2", headers=ADMIN, json=command)
        assert rejected.json()["status_code"] == 26135
        monkeypatch.setenv("BS_DSH_MODEL_AUDIT_KEYS", valid)
        retried = await client.put(BASE + "/settings/2", headers=ADMIN, json=command)
        assert retried.json()["data"] == {"mode": "CONTENT", "version": 2, "content_available": True}


async def test_key_loss_is_reported_without_rewriting_mode_or_breaking_model_calls(monkeypatch):
    encoded = base64.b64encode(bytes(range(32))).decode()
    monkeypatch.setenv("BS_DSH_MODEL_AUDIT_KEYS", json.dumps({"active": encoded}))
    async with fixture("OFF") as (harness, client, objects):
        settings = bind_production_modes(harness, monkeypatch, "active")
        command = {"operation_id": "readiness-enable", "expected_version": 1, "mode": "CONTENT"}
        enabled = await client.put(BASE + "/settings/2", headers=ADMIN, json=command)
        assert enabled.json()["data"] == {"mode": "CONTENT", "version": 2, "content_available": True}
        assert encoded not in enabled.text
        monkeypatch.setenv("BS_DSH_MODEL_AUDIT_KEYS", "{}")
        lost = await client.get(BASE + "/settings", headers=LOCAL_ADMIN)
        assert lost.json()["data"] == {"mode": "CONTENT", "version": 2, "content_available": False}
        replay = await client.put(BASE + "/settings/2", headers=ADMIN, json=command)
        assert replay.json()["data"] == lost.json()["data"]

        runtime = ModelAuditRuntime(settings, None)
        runtime.modes.read_snapshot = harness.read_mode
        runtime.queue, runtime.evidence_queue, runtime.activity = harness.queue, harness.evidence, None
        harness.service.audit_factory = runtime.capture
        response = await call(client)
        assert response.status_code == 200 and harness.calls == 1
        await harness.drain()
        request_id = response.headers["x-request-id"]
        record = (await client.get(BASE + "/requests/" + request_id, headers=ADMIN)).json()["data"]
        assert record["effective_mode"] == "CONTENT" and record["content_status"] == "PARTIAL"
        assert record["model_result"] == "SUCCEEDED"
        assert record["input_bytes"] == record["output_bytes"] == 0
        assert objects.data == {}
        saved = await client.put(
            BASE + "/settings/2", headers=ADMIN, json={"operation_id": "disable", "expected_version": 2, "mode": "OFF"}
        )
        assert saved.json()["data"] == {"mode": "OFF", "version": 3, "content_available": False}
