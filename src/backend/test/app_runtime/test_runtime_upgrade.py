"""覆盖 AC: AC-03、AC-08、AC-10、AC-13、AC-46、AC-57、AC-60。"""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "upgrade_vibe_runtime", Path(__file__).parents[2] / "scripts/upgrade_vibe_runtime.py"
)
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


def test_inventory_scope_and_immutable_execution_are_required():
    item = {
        "app_id": "a",
        "version_id": "v",
        "image_id": "sha256:" + "a" * 64,
        "labels": {"bisheng.app.id": "a", "bisheng.version.id": "v"},
    }
    document = {"schema_version": 1, "node_id": "node", "engine_id": "engine", "applications": [item]}
    assert upgrade.validate_inventory(document) == document
    with pytest.raises(ValueError, match="duplicate"):
        upgrade.validate_inventory({**document, "applications": [item, item]})
    with pytest.raises(ValueError, match="scope"):
        upgrade.validate_inventory({**document, "applications": [{**item, "version_id": "foreign"}]})


def test_apply_requires_reviewed_hash_and_explicit_maintenance(tmp_path, monkeypatch):
    source = tmp_path / "inventory.json"
    source.write_text('{"schema_version":1}')
    monkeypatch.setattr(
        "sys.argv",
        [
            "upgrade",
            "--inventory",
            str(source),
            "--base-url",
            "http://example",
            "--report",
            str(tmp_path / "report.json"),
            "--apply",
        ],
    )
    with pytest.raises(SystemExit) as result:
        upgrade.main()
    assert result.value.code == 2
