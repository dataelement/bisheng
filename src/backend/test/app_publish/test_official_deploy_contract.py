"""F119 AC-01, AC-06, AC-35: platform-distributed examples follow the bundle contract."""

import runpy
from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parents[2] / "bisheng/dev_toolkit/skills"


@pytest.mark.parametrize("sample", ["deploy-hosting/example", "platform-wiring/example", "platform-wiring/example-sdk"])
def test_shipped_manifest_uses_v2_bundle(sample):
    from bisheng.app_publish.domain.schemas.app_manifest import AppManifest

    raw = yaml.safe_load((SKILLS / sample / "bisheng-app.yaml").read_text())
    assert raw["manifest_version"] == 2
    assert AppManifest.model_validate(raw).delivery_mode == "bundle"


@pytest.mark.parametrize("sample", ["deploy-hosting/example", "platform-wiring/example"])
def test_write_example_requires_injected_database(monkeypatch, sample):
    monkeypatch.delenv("BISHENG_APP_DB_PATH", raising=False)
    with pytest.raises(RuntimeError, match="BISHENG_APP_DB_PATH"):
        runpy.run_path(str(SKILLS / sample / "main.py"))


def test_database_example_keeps_data_across_application_reload(monkeypatch, tmp_path):
    database = tmp_path / "app.db"
    monkeypatch.setenv("BISHENG_APP_DB_PATH", str(database))
    path = str(SKILLS / "deploy-hosting/example/main.py")
    assert runpy.run_path(path)["bump_and_read"]() == 1
    assert runpy.run_path(path)["bump_and_read"]() == 2
    assert database.is_file()


def test_deployment_guidance_describes_offline_materials_and_new_default():
    text = (SKILLS / "deploy-hosting/SKILL.md").read_text()
    assert "manifest_version: 2" in text
    assert "offline_artifacts" in text
    assert "source-image" in text
