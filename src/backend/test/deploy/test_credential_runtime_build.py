"""Option C: no Go credential-runtime delivery; host uses Python credential_tool only."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_dockerfile_does_not_build_or_copy_credential_runtime():
    text = (ROOT / "src/backend/Dockerfile").read_text()
    assert "credential-runtime-build" not in text
    assert "/opt/bisheng/credential-runtime" not in text
    assert "tools/credential-runtime" not in text


def test_runtime_helper_does_not_extract_go_binary():
    text = (ROOT / "docker/lib/credential-runtime.sh").read_text()
    assert "credential_runtime_prepare()" in text
    assert "/opt/bisheng/credential-runtime" not in text
    assert "go build" not in text and "pip install" not in text
    assert "credential_compose_service_ids" in text


def test_seed_discovers_native_services_without_compose_interpolation():
    text = (ROOT / "docker/lib/credential-runtime.sh").read_text()
    assert "credential_compose_service_ids" in text
    assert "label=com.docker.compose.service=$service" in text
    seed = text.split("credential_runtime_seed_bundle()", 1)[1].split("credential_runtime_publish_bundle()", 1)[0]
    assert "compose ps" not in seed
    assert "credential_compose_service_ids redis" in seed
    assert 'credential_compose_service_ids "$role"' in seed


def test_go_credential_runtime_source_removed_from_delivery():
    assert not (ROOT / "src/backend/tools/credential-runtime").exists()
