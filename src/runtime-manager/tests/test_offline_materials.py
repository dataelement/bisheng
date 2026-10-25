"""覆盖 AC: AC-14、AC-15、AC-27、AC-28、AC-29、AC-30、AC-31、AC-55、AC-59。"""

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "runtime_materials", Path(__file__).parents[1] / "tools/runtime_materials.py"
)
materials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(materials)


def test_pack_verifies_content_and_fixed_target(tmp_path):
    profile = {"profile_id": "profile", "profile_digest": "digest", "platform": "linux/arm64", "abi": "cp311"}
    root = tmp_path / "materials"
    root.mkdir()
    (root / "one.whl").write_bytes(b"test-wheel")
    result = materials.pack(root, profile, tmp_path / "pack.tar.gz")
    assert materials.verify(result["path"], profile)["files"]["one.whl"]["size"] == 10
    with pytest.raises(ValueError, match="profile"):
        materials.verify(result["path"], {**profile, "platform": "linux/amd64"})


def test_sensitive_config_file_is_refused(tmp_path):
    profile = {"profile_id": "profile", "profile_digest": "digest", "platform": "linux/arm64", "abi": "cp311"}
    root = tmp_path / "materials"
    root.mkdir()
    (root / ".npmrc").write_text("registry=example")
    with pytest.raises(ValueError, match="credential"):
        materials.pack(root, profile, tmp_path / "pack.tar.gz")


def test_catalog_requires_both_native_architectures(tmp_path):
    path = tmp_path / "arm.json"
    path.write_text(json.dumps({"platform": "linux/arm64", "images": {}}))
    with pytest.raises(ValueError, match="both native"):
        materials.catalog([path], tmp_path / "profiles.json", 1)


def test_catalog_import_sets_defaults_with_expected_generation(monkeypatch):
    calls = []

    def request(base, path, **kwargs):
        calls.append((path, kwargs))
        if path.endswith("/defaults"):
            return [{"language": "python3.11", "profile_id": "old", "generation": 4}]
        return {"id": "new"}

    monkeypatch.setattr(materials, "request", request)
    result = materials.import_catalog(
        "https://platform",
        {"profiles": [{"code": "python", "revision": 2}], "defaults": {"python3.11": "python@2"}},
        set_defaults=True,
    )
    assert result == {"python@2": "new"}
    assert calls[-1] == (
        "/api/v1/runtime/profiles/default",
        {"method": "PUT", "document": {"language": "python3.11", "profile_id": "new", "expected_generation": 4}},
    )


def test_offline_preparation_validates_installation_without_network(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "package.json").write_text("{}")
    calls = []
    monkeypatch.setattr(materials.subprocess, "run", lambda command, **kwargs: calls.append(command))
    materials.prepare_offline(
        source,
        tmp_path / "materials",
        {"platform": "linux/arm64", "preparer_image_id": "sha256:test", "language": "node20"},
        "sha256:test",
    )
    assert len(calls) == 2
    assert calls[0][-2:] == ["download", "node20"]
    assert calls[1][-2:] == ["lock", "node20"]
    assert calls[1][calls[1].index("--network") + 1] == "none"
    assert not any(f"src={source},dst=/workspace/app" in arg for arg in calls[0])
