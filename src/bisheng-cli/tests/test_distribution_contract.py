"""F119 覆盖 AC: AC-01, AC-27: test the wheel actually downloaded by platform users."""

import hashlib
import json
import subprocess
import sys
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "src/backend/bisheng/dev_toolkit/artifacts"


def test_source_metadata_wheel_and_platform_manifest_agree():
    import bisheng_cli

    distribution = json.loads((ARTIFACTS / "manifest.json").read_text())["cli"]
    wheel = ARTIFACTS / distribution["filename"]
    assert distribution["version"] == bisheng_cli.__version__
    assert (
        tomllib.loads((ROOT / "src/bisheng-cli/pyproject.toml").read_text())["project"]["version"]
        == bisheng_cli.__version__
    )
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == distribution["sha256"]
    with zipfile.ZipFile(wheel) as archive:
        metadata = Parser().parsestr(
            archive.read(next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))).decode()
        )
        assert metadata["Version"] == distribution["version"]
        assert archive.read("bisheng_cli/errors.py") == (ROOT / "src/bisheng-cli/bisheng_cli/errors.py").read_bytes()


def test_downloaded_wheel_has_the_new_error_behavior_in_an_isolated_python():
    distribution = json.loads((ARTIFACTS / "manifest.json").read_text())["cli"]
    wheel = ARTIFACTS / distribution["filename"]
    script = "import sys; sys.path.insert(0, sys.argv[1]); from bisheng_cli.errors import error_from_platform,render_human; err=error_from_platform(16124,'failed',details={'reason':'startup_exited','tail':[]}); assert err.code==16124 and err.exit_code==10; text=render_human(err); assert 'startup_exited' in text and '暂无可用' in text"
    subprocess.run([sys.executable, "-I", "-c", script, str(wheel)], check=True, capture_output=True)


def test_cli_packaging_preserves_the_existing_sdk_distribution():
    manifest = json.loads((ARTIFACTS / "manifest.json").read_text())
    previous = json.loads(
        subprocess.check_output(
            ["git", "show", "HEAD:src/backend/bisheng/dev_toolkit/artifacts/manifest.json"], cwd=ROOT
        )
    )
    assert manifest["sdk"] == previous["sdk"]
    sdk = ARTIFACTS / manifest["sdk"]["filename"]
    assert hashlib.sha256(sdk.read_bytes()).hexdigest() == manifest["sdk"]["sha256"]
