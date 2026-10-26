"""T013 — project layer: manifest fast-fail and the per-project app identity.

CON-1's consequence in one line: the CLI checks that the manifest **exists, parses,
and names three fields**, and nothing else. The authoritative schema belongs to
F055's hosted precheck, and `extra='forbid'` there means any field the CLI
invents locally becomes a rejected upload.
"""

from __future__ import annotations

import json

import pytest

from bisheng_cli import credentials, project
from bisheng_cli.errors import EXIT_LOCAL_INVALID, EXIT_USAGE, CliError

BASE = "http://114.test:7860"

MINIMAL = "name: demo\nruntime: python3.11\nport: 8080\n"


def _write(root, text: str):
    root.mkdir(parents=True, exist_ok=True)
    (root / project.MANIFEST_NAME).write_text(text, encoding="utf-8")
    return root


def test_missing_manifest_refused_locally_without_upload(tmp_path) -> None:
    # The `no_network` sentinel is what proves "without upload": any request at
    # all would raise from the transport instead of reaching this assertion.
    (tmp_path / "app").mkdir()
    with pytest.raises(CliError) as excinfo:
        project.load_manifest(tmp_path / "app")
    assert excinfo.value.exit_code == EXIT_LOCAL_INVALID
    assert project.MANIFEST_NAME in excinfo.value.message


def test_unparsable_yaml_refused_with_line_info(tmp_path) -> None:
    root = _write(tmp_path / "app", "name: demo\n  bad: [unclosed\n")
    with pytest.raises(CliError) as excinfo:
        project.load_manifest(root)
    assert excinfo.value.exit_code == EXIT_LOCAL_INVALID
    assert "line" in excinfo.value.message.lower() or "行" in excinfo.value.message


@pytest.mark.parametrize("missing", ["name", "runtime", "port"])
def test_each_of_name_runtime_port_missing_is_named_in_the_error(tmp_path, missing: str) -> None:
    lines = [line for line in MINIMAL.splitlines() if not line.startswith(missing + ":")]
    root = _write(tmp_path / missing, "\n".join(lines) + "\n")
    with pytest.raises(CliError) as excinfo:
        project.load_manifest(root)
    assert missing in excinfo.value.message
    for other in {"name", "runtime", "port"} - {missing}:
        assert other not in excinfo.value.message


def test_safe_load_only_rejects_python_object_tag(tmp_path) -> None:
    # full_load / unsafe_load turn a manifest into remote code execution; the
    # refusal has to come from safe_load itself, not from a blocklist we maintain.
    root = _write(tmp_path / "app", "name: !!python/object/apply:os.system ['echo pwned']\n")
    with pytest.raises(CliError) as excinfo:
        project.load_manifest(root)
    assert excinfo.value.exit_code == EXIT_LOCAL_INVALID


def test_optional_fields_not_validated_locally(tmp_path) -> None:
    root = _write(
        tmp_path / "app",
        MINIMAL + "tier: nonsense\ncapabilities: [whatever]\ndatabase: 3\negress: []\n",
    )
    manifest = project.load_manifest(root)
    # Nothing invented, nothing defaulted: a locally-added default is exactly how
    # "passes locally, rejected on upload" is manufactured.
    assert manifest["tier"] == "nonsense"
    assert set(manifest) == {"name", "runtime", "port", "tier", "capabilities", "database", "egress"}


def test_app_json_written_and_read_per_base_url(tmp_path) -> None:
    root = _write(tmp_path / "app", MINIMAL)
    project.save_app_ref(root, BASE, app_id="app-1", app_name="问卷", slug="wenjuan", last_deployment_id="dep-1")
    raw = json.loads((root / ".bisheng" / "app.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1
    entry = raw["apps"][BASE]
    assert entry["app_id"] == "app-1" and entry["slug"] == "wenjuan" and entry["updated_at"]
    assert project.read_app_ref(root, BASE)["app_name"] == "问卷"


def test_app_json_key_uses_the_same_base_url_normaliser_as_credentials(tmp_path) -> None:
    # One function, not two implementations that agree today.
    assert project.normalise_base_url is credentials.normalise_base_url
    root = _write(tmp_path / "app", MINIMAL)
    project.save_app_ref(root, "http://114.test:7860/", app_id="app-1")
    assert project.read_app_ref(root, "HTTP://114.test:7860")["app_id"] == "app-1"


def test_second_platform_does_not_clobber_the_first(tmp_path) -> None:
    root = _write(tmp_path / "app", MINIMAL)
    project.save_app_ref(root, BASE, app_id="app-1")
    project.save_app_ref(root, "http://other.test", app_id="app-2")
    assert project.read_app_ref(root, BASE)["app_id"] == "app-1"


def test_explicit_app_id_overrides_saved_one(tmp_path) -> None:
    root = _write(tmp_path / "app", MINIMAL)
    project.save_app_ref(root, BASE, app_id="app-saved")
    assert project.resolve_app_id(root, BASE, explicit="app-forced") == "app-forced"


def test_resolve_app_id_returns_none_when_unknown_for_first_deploy(tmp_path) -> None:
    root = _write(tmp_path / "app", MINIMAL)
    assert project.resolve_app_id(root, BASE, explicit=None) is None


def test_missing_app_id_asks_for_explicit_flag(tmp_path) -> None:
    # A copied project has no saved identity. Guessing one would silently deploy
    # over whatever app happened to match.
    root = _write(tmp_path / "app", MINIMAL)
    with pytest.raises(CliError) as excinfo:
        project.require_app_id(root, BASE, explicit=None)
    assert excinfo.value.exit_code == EXIT_USAGE
    assert "--app-id" in excinfo.value.next_step


def test_find_project_root_rejects_a_path_that_is_not_a_directory(tmp_path) -> None:
    target = tmp_path / "not-a-dir"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(CliError) as excinfo:
        project.find_project_root(str(target))
    assert excinfo.value.exit_code == EXIT_LOCAL_INVALID
