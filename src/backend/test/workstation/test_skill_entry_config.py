"""F035 (v2.6): the client 添加技能 (Add Skill) entry is gated by a new
`skillEntry` toggle on the daily workstation config, defaulting to off.

These tests pin the storage round-trip and `exclude_unset` semantics that the
public /workstation/config endpoint relies on:
- a saved skillEntry survives parse_config and is emitted to the frontend;
- a legacy config (no skillEntry key) stays unset, so the dump omits it and the
  frontend default (off) applies.
"""

import json
from types import SimpleNamespace

from bisheng.api.v1.schemas import WorkstationConfig, WSPrompt


def _raw(payload: dict) -> SimpleNamespace:
    """Mimic the DB row object parse_config consumes (`.value` is a JSON str)."""
    return SimpleNamespace(value=json.dumps(payload))


def test_parse_config_roundtrips_enabled_skill_entry():
    # `tools: []` keeps parse_config off the GptsToolsDao seeding path (no DB).
    cfg = WorkStationService_parse({"tools": [], "skillEntry": {"enabled": True}})

    assert cfg is not None
    assert cfg.skillEntry is not None
    assert cfg.skillEntry.enabled is True
    # Explicitly set → surfaced to the frontend via exclude_unset dump. The
    # nested `prompt` stays unset (never sent), so the client reads enabled only.
    assert cfg.model_dump(exclude_unset=True)["skillEntry"] == {"enabled": True}


def test_parse_config_legacy_config_omits_skill_entry():
    cfg = WorkStationService_parse({"tools": []})

    assert cfg is not None
    # Absent in storage → unset → frontend never receives it → default off.
    assert cfg.skillEntry is None
    assert "skillEntry" not in cfg.model_dump(exclude_unset=True)


def test_skill_entry_defaults_off_when_constructed_blank():
    # A bare config (e.g. partial admin payload) must not silently enable the entry.
    assert WorkstationConfig().skillEntry is None


def test_workstation_config_accepts_skill_entry_wsprompt():
    cfg = WorkstationConfig(skillEntry=WSPrompt(enabled=False, prompt=""))

    assert cfg.skillEntry.enabled is False


def WorkStationService_parse(payload: dict):
    # Imported lazily so the heavy service module loads once per call site only.
    from bisheng.workstation.domain.services.workstation_service import WorkStationService

    return WorkStationService.parse_config(_raw(payload))
