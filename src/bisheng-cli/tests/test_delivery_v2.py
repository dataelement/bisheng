"""Scaffold a bundle without changing existing manifests or packing local environments."""

import io
import json

import pytest
import yaml


@pytest.mark.parametrize("runtime", ["python3.11", "node20", "static"])
def test_init_defaults_to_v2_bundle(tmp_path, runtime):
    """AC-11, AC-17: new projects use the explicit bundle startup contract."""
    from bisheng_cli.main import run

    out = io.StringIO()
    err = io.StringIO()
    root = tmp_path / "new-app"
    assert run(["init", str(root), "--runtime", runtime, "--json"], stdout=out, stderr=err) == 0
    manifest = yaml.safe_load((root / "bisheng-app.yaml").read_text())
    assert manifest["manifest_version"] == 2
    assert manifest["delivery"]["mode"] == "bundle"
    assert manifest["delivery"]["startup"]["command"]
    assert json.loads(out.getvalue().splitlines()[-1])["ok"] is True


def test_init_preserves_existing_files(tmp_path):
    """AC-13, AC-60: initialization never rewrites an existing v1 application."""
    from bisheng_cli.errors import CliError
    from bisheng_cli.project import initialize_project

    path = tmp_path / "bisheng-app.yaml"
    path.write_text("manifest_version: 1\n")
    with pytest.raises(CliError):
        initialize_project(tmp_path, "python3.11")
    assert path.read_text() == "manifest_version: 1\n"
