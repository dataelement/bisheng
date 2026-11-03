"""覆盖 AC: AC-01、AC-03、AC-04、AC-05、AC-54、AC-55、AC-56、AC-57、AC-58。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def section(name):
    text = (ROOT / "docker/docker-compose.yml").read_text()
    start = text.index("  " + name + ":")
    end = text.find("\n  ", start + 3)
    while end >= 0 and text[end + 3 : end + 4] == " ":
        end = text.find("\n  ", end + 1)
    return text[start : end if end >= 0 else len(text)]


def test_formal_compose_uses_published_images_without_manager_minio():
    for name in ["runtime-manager", "egress-proxy", "app-proxy"]:
        body = section(name)
        assert "image:" in body and "build:" not in body
    assert "RTM_MINIO_" not in section("runtime-manager")
    assert "/app-data" not in section("egress-proxy")
    assert "RTM_DOCKER_HOST" not in section("egress-proxy")
    assert "APP_PROXY_MANAGER_SECRET" not in section("app-proxy")


def test_native_jobs_and_frozen_sdk_are_in_delivery():
    workflow = (ROOT / ".github/workflows/runtime-images.yml").read_text()
    assert "ubuntu-22.04-arm" in workflow and "arch: amd64" in workflow
    dockerfile = (ROOT / "src/app-runtime/python3.11/Dockerfile").read_text()
    assert "bisheng_sdk-0.1.1" in dockerfile and "AS preparer" in dockerfile
    assert "docker.sock" not in section("runtime-manager")
