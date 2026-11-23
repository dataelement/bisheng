"""F004: the ``unified_runtime_enabled`` switch is gone; records that still store the key keep working.

Until 2026-11-20 the daily workstation record (``workstation`` key) could carry
``"unified_runtime_enabled": true | false``, and many installs have one. Reading
such a record must not fail, the value must have no effect, the admin save must
not write the key back, and ``GET /workstation/config`` must not return it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from bisheng.api.v1.schemas import WorkstationConfig
from bisheng.workstation.domain.services.workstation_service import WorkStationService


@pytest.mark.parametrize("leftover", [True, False, "definitely", None])
def test_stored_record_with_the_leftover_key_still_parses(leftover):
    stored = json.dumps({"welcomeMessage": "hi", "unified_runtime_enabled": leftover})

    config = WorkStationService.parse_config(SimpleNamespace(value=stored))

    assert config.welcomeMessage == "hi"
    assert "unified_runtime_enabled" not in WorkstationConfig.model_fields
    # What the public config endpoint returns is this dump: the key is not in it.
    assert "unified_runtime_enabled" not in config.model_dump(exclude_unset=True)
    assert "unified_runtime_enabled" not in config.model_dump()


@pytest.mark.parametrize("leftover", [True, False])
async def test_admin_save_drops_the_leftover_key(monkeypatch, leftover):
    """The record is rewritten from the request model, so the next save removes the key."""
    saved: dict = {}

    async def fake_upsert(key, *, payload):
        saved["payload"] = payload

    async def fake_meta():
        return WorkstationConfig(**json.loads(saved["payload"])), False, 5, True, False

    monkeypatch.setattr(WorkStationService, "_aupsert_tenant_config", fake_upsert)
    monkeypatch.setattr(WorkStationService, "get_daily_chat_config_with_meta", fake_meta)

    # A client that still echoes the key back (an old admin page build) is accepted too.
    request = WorkstationConfig(**{"welcomeMessage": "new", "unified_runtime_enabled": leftover})
    result = await WorkStationService.update_daily_chat_config(request)

    stored = json.loads(saved["payload"])
    assert stored["welcomeMessage"] == "new"
    assert "unified_runtime_enabled" not in stored
    assert result.welcomeMessage == "new"
