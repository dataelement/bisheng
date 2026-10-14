"""New-install seed defaults to container; upgrades must not rewrite extra (F068 T027)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
_SEED = _BACKEND / "bisheng" / "database" / "data" / "t_gpts_tools.json"
_INIT = _BACKEND / "bisheng" / "common" / "init_data.py"
_TOOL_KEY = "bisheng_code_interpreter"


def _seed_items() -> list[dict]:
    return json.loads(_SEED.read_text(encoding="utf-8"))


def _extra_payload(row: dict):
    extra = row.get("extra")
    if extra is None or extra == "":
        return {}
    if isinstance(extra, dict):
        return extra
    return json.loads(extra)


def test_seed_json_code_interpreter_defaults_to_container():
    rows = [item for item in _seed_items() if item.get("tool_key") == _TOOL_KEY]
    assert len(rows) == 1
    assert _extra_payload(rows[0]).get("type") == "container"


def test_seed_json_does_not_set_container_on_other_tools():
    for item in _seed_items():
        if item.get("tool_key") == _TOOL_KEY:
            continue
        assert _extra_payload(item).get("type") != "container"


def test_init_data_skips_seed_when_gpts_tools_already_exist():
    source = _INIT.read_text(encoding="utf-8")
    assert "if not preset_tools:" in source
    assert "t_gpts_tools.json" in source


def test_init_data_does_not_update_or_upsert_existing_tool_extra():
    source = _INIT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "extra":
            raise AssertionError("init_data.py must not write GptsTools.extra on upgrade")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "values":
            for kw in node.keywords:
                assert kw.arg != "extra", "init_data.py must not UPDATE extra"
    lowered = source.lower()
    assert "upsert" not in lowered
    assert "on conflict" not in lowered
    assert "on duplicate" not in lowered
    assert "update extra" not in lowered
