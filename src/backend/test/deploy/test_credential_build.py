"""Build artifact security: AC-01, AC-06, AC-42."""

import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def scanner():
    spec = importlib.util.spec_from_file_location("image_secrets", BACKEND / "scripts/check_image_secrets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def archive(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return stream.getvalue()


def test_source_secret_detection_is_redacted(scanner, tmp_path):
    key = Fernet.generate_key()
    (tmp_path / "settings.py").write_bytes(b'secret_key = "' + key + b'"\n')
    findings = scanner.scan_source(tmp_path)
    assert findings and "settings.py" in str(findings)
    assert key.decode() not in str(findings)


def test_lower_layer_secret_survives_whiteout(scanner, tmp_path):
    key = Fernet.generate_key()
    image = tmp_path / "image.tar"
    image.write_bytes(
        archive(
            {
                "manifest.json": json.dumps([{"Layers": ["old/layer.tar", "new/layer.tar"]}]).encode(),
                "old/layer.tar": archive({"app/settings.py": b'secret_key = "' + key + b'"'}),
                "new/layer.tar": archive({"app/.wh.settings.py": b""}),
            }
        )
    )
    findings = scanner.scan_image(image)
    assert any("old/layer.tar" in item for item in findings)
    assert key.decode() not in str(findings)


def test_sensitive_local_configuration_is_detected(scanner, tmp_path):
    target = tmp_path / "bisheng/config.yaml"
    target.parent.mkdir()
    target.write_text("database_url: hidden\n")
    assert scanner.scan_source(tmp_path)


def test_unsupported_archive_is_not_success(scanner, tmp_path):
    image = tmp_path / "not-image.tar"
    image.write_bytes(archive({"unrelated": b"data"}))
    with pytest.raises(ValueError):
        scanner.scan_image(image)


def test_clean_artifact(scanner, tmp_path):
    tmp_path = tmp_path / "clean"
    tmp_path.mkdir()
    (tmp_path / "code.py").write_text("def encrypt(value): return value\n")
    assert scanner.scan_source(tmp_path) == []
    image = tmp_path / "image.tar"
    image.write_bytes(
        archive(
            {
                "manifest.json": json.dumps([{"Layers": ["one/layer.tar"]}]).encode(),
                "one/layer.tar": archive({"app/code.py": b"# no secret\n"}),
            }
        )
    )
    assert scanner.scan_image(image) == []


def test_dockerignore_excludes_runtime_inputs():
    entries = (BACKEND / ".dockerignore").read_text().splitlines()
    for required in ["bisheng/config.yaml", ".env", ".env.*", "secrets/", ".generated/"]:
        assert required in entries


def test_image_config_environment_is_also_scanned(scanner, tmp_path):
    key = Fernet.generate_key()
    image = tmp_path / "metadata.tar"
    image.write_bytes(
        archive(
            {
                "manifest.json": json.dumps([{"Config": "config.json", "Layers": ["layer.tar"]}]).encode(),
                "config.json": json.dumps({"config": {"Env": ["EXTERNAL_KEY=" + key.decode()]}}).encode(),
                "layer.tar": archive({"app/code.py": b"# safe"}),
            }
        )
    )
    findings = scanner.scan_image(image, (key,))
    assert any("config.json" in item for item in findings)
    assert key.decode() not in str(findings)
