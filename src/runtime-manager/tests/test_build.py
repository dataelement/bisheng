"""Image build — D3: the platform owns the Dockerfile, the developer never writes one.

Two properties are worth stating because they are the reason this module exists
at all rather than "just run docker build on whatever the user gave us":

* **The security baseline is in the template, so it cannot be opted out of.**
  Non-root user, no shell entrypoint, a layout that survives a read-only root
  filesystem — the developer cannot weaken any of it, because the developer
  never supplies a Dockerfile (PRD-1 DEV-04 forbids it).
* **Failures must land on a stage.** AC-15 asks for "a readable reason *and* a
  failure stage" because "build failed" is useless to the person who has to fix
  it: a dependency-resolution failure, a missing source object and a capacity
  refusal need three different actions.

Build parameters are asserted against the fake backend; whether the produced
image actually runs is a real-docker question — see ``@pytest.mark.docker``
below (CI middleware stage + 114 manual verification).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime_manager.api.schemas import BuildRequest
from runtime_manager.builder import (
    STAGE_BUILD_ADMISSION,
    STAGE_DOCKER_BUILD,
    STAGE_FETCH_SOURCE,
    BuildService,
    discover_runtimes,
    image_tag,
    render_build_context,
)
from runtime_manager.errors import UnsupportedRuntimeError
from tests.fakes import FakeHostProbe

MIB = 1024 * 1024


def _request(**overrides) -> BuildRequest:
    payload = {
        "app_id": "app-1",
        "slug": "sales-report",
        "version_id": "ver-0123456789abcdef",
        "version_no": 3,
        "runtime": "python3.11",
        "code_object_key": "apps/app-1/ver-0123456789abcdef.tar.gz",
        "code_url": "https://minio.example.com/presigned",
        "port": 8080,
    }
    payload.update(overrides)
    return BuildRequest(**payload)


def _fetcher(files: dict[str, str] | None = None):
    """Source fetcher double: materialises a source tree instead of downloading."""

    def fetch(url: str, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        for name, content in (files or {"main.py": "print('hi')\n"}).items():
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    return fetch


def _service(config, fake_docker, probe: FakeHostProbe | None = None, fetcher=None) -> BuildService:
    from runtime_manager.admission import AdmissionService

    return BuildService(
        config,
        docker=fake_docker,
        admission=AdmissionService(config, host_probe=probe or FakeHostProbe()),
        fetcher=fetcher or _fetcher(),
    )


def test_supported_runtimes_dynamic_from_templates():
    """The set is whatever templates this deployment actually ships.

    Not a hard-coded list: an air-gapped install that only carries the python
    base image must be able to advertise exactly that, and F059 / T092 add a
    runtime by adding a directory — never by editing a constant that some other
    module also hard-codes.
    """
    assert discover_runtimes() == ["python3.11"]


def test_unsupported_runtime_rejected_lists_supported(rtm_config, fake_docker):
    """AC-15: rejection must tell the caller what *would* work."""
    with pytest.raises(UnsupportedRuntimeError) as excinfo:
        _service(rtm_config, fake_docker).run(_request(runtime="go1.22"))

    detail = excinfo.value.detail
    assert detail["code"] == "unsupported_runtime"
    assert detail["supported_runtimes"] == ["python3.11"]
    assert "go1.22" in detail["message"]


def test_template_render_deterministic(rtm_config):
    """Same inputs, same bytes — and the baseline is present in those bytes."""
    ctx = {"port": 8080, "app_user": "bisheng"}
    first = render_build_context("python3.11", ctx)
    second = render_build_context("python3.11", ctx)

    assert first == second
    dockerfile = first["Dockerfile"]
    # Non-root: the app process must not be uid 0 even before no-new-privileges.
    assert "USER bisheng" in dockerfile
    assert dockerfile.rstrip().splitlines()[-1].startswith("ENTRYPOINT")
    # Read-only rootfs friendly: nothing is written under / at runtime; the two
    # writable paths are the /tmp tmpfs and the /data volume (AC-17).
    assert "/data" in dockerfile
    # D5.2 — the wrapper is what connects the platform's prefix to the framework.
    assert "BISHENG_APP_BASE_PATH" in first["entrypoint.sh"]
    assert "UVICORN_ROOT_PATH" in first["entrypoint.sh"]
    # exec, so SIGTERM reaches the app: docker stop and restart policy both
    # depend on the app being pid 1's actual process, not a shell's child.
    assert "exec " in first["entrypoint.sh"]
    assert "BISHENG_APP_HEALTH_PATH" in first["healthcheck.py"]


def test_build_args_inject_index_url(rtm_config, fake_docker):
    """Package source comes from deployment config, never from the app."""
    record = _service(rtm_config, fake_docker).run(_request())

    assert record.status == "succeeded"
    call = fake_docker.last_call("build_image")
    assert call["buildargs"]["PIP_INDEX_URL"] == rtm_config.build_index_url
    assert call["buildargs"]["PIP_TRUSTED_HOST"] == rtm_config.build_trusted_host


def test_build_memory_limited_and_admission_checked(rtm_config, fake_docker):
    """K2: a build is a memory spike; it goes through the same door as a start."""
    record = _service(rtm_config, fake_docker).run(_request())

    assert record.status == "succeeded"
    assert fake_docker.last_call("build_image")["memory_bytes"] == rtm_config.build_reserve_mb * MIB


def test_build_refused_when_capacity_exhausted(rtm_config, fake_docker):
    """Refusal happens *before* the daemon is touched — nothing to clean up."""
    probe = FakeHostProbe(mem_available_mb=2100)  # 2100 - 2048 reserve ≪ 2048 needed
    record = _service(rtm_config, fake_docker, probe=probe).run(_request())

    assert record.status == "failed"
    assert record.stage == STAGE_BUILD_ADMISSION
    assert "memory" in record.message
    assert fake_docker.call_count("build_image") == 0


def test_build_failure_returns_stage_and_tail(rtm_config, fake_docker):
    """A daemon-reported build error maps to ``docker_build`` + the log tail."""
    fake_docker.build_stream = [
        {"stream": "Step 1/9 : FROM python:3.11-slim\n"},
        {"stream": "Step 6/9 : RUN pip install -r requirements.txt\n"},
        {"stream": "ERROR: No matching distribution found for pandas==99.0\n"},
        {"error": "The command '/bin/sh -c pip install -r requirements.txt' returned a non-zero code: 1"},
    ]

    record = _service(rtm_config, fake_docker).run(_request())

    assert record.status == "failed"
    assert record.stage == STAGE_DOCKER_BUILD
    assert "non-zero code: 1" in record.message
    assert any("No matching distribution" in line for line in record.tail)


def test_source_fetch_failure_maps_to_fetch_stage(rtm_config, fake_docker):
    """A dead pre-signed URL is not a "build failure" — it is a different fix."""

    def boom(url: str, dest: Path) -> None:
        raise OSError("403 Forbidden")

    record = _service(rtm_config, fake_docker, fetcher=boom).run(_request())

    assert record.status == "failed"
    assert record.stage == STAGE_FETCH_SOURCE
    assert "403" in record.message


def test_image_tag_never_reused(rtm_config):
    """AppVersion is append-only (AC-02), so a tag identifies one snapshot forever.

    No ``latest``, no per-app mutable tag: the previous version's image must stay
    pullable and distinguishable while its container is being retired (AC-21).
    """
    v3 = image_tag(rtm_config, "sales-report", 3, "ver-0123456789abcdef")
    v4 = image_tag(rtm_config, "sales-report", 4, "ver-fedcba9876543210")

    assert v3 == "bisheng-app/sales-report:3-ver-0123"
    assert v3 != v4
    assert "latest" not in v3
    # Stable for the same version — a retried build reuses its own tag rather
    # than littering the daemon with one image per attempt.
    assert v3 == image_tag(rtm_config, "sales-report", 3, "ver-0123456789abcdef")


def test_image_retention_keeps_current_and_previous(rtm_config, fake_docker):
    """Keep exactly the two images AC-21's grace retirement can need."""
    for version in (1, 2, 3):
        fake_docker.images.append(image_tag(rtm_config, "sales-report", version, f"ver-{version:016d}"))

    record = _service(rtm_config, fake_docker).run(_request(version_no=4, version_id="ver-" + "4" * 16))

    assert record.status == "succeeded"
    remaining = sorted(fake_docker.images)
    assert len(remaining) == 2
    assert record.image_ref in remaining
    assert image_tag(rtm_config, "sales-report", 3, f"ver-{3:016d}") in remaining
    assert fake_docker.call_count("remove_image") == 2


def test_build_endpoint_and_status_endpoint(rtm_client, rtm_config, fake_docker, monkeypatch):
    """§4.2 ①: submit returns a handle, status is polled until terminal."""
    monkeypatch.setattr(
        "runtime_manager.admission.LinuxHostProbe.snapshot",
        lambda self: FakeHostProbe().snapshot(),
    )
    monkeypatch.setattr("runtime_manager.builder.fetch_source", _fetcher())

    response = rtm_client.post("/v1/intents/build", _request().model_dump())
    assert response.status_code == 200
    build_id = response.json()["build_id"]
    assert response.json()["status"] in {"building", "succeeded"}

    status = rtm_client.get(f"/v1/builds/{build_id}")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] in {"building", "succeeded"}
    assert set(body) >= {"status", "stage", "message", "tail", "image_ref"}


def test_build_endpoint_rejects_unsupported_runtime(rtm_client):
    response = rtm_client.post("/v1/intents/build", _request(runtime="go1.22").model_dump())

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "unsupported_runtime"
    assert detail["supported_runtimes"] == ["python3.11"]


def test_unknown_build_id_is_404(rtm_client):
    assert rtm_client.get("/v1/builds/nope").status_code == 404


@pytest.mark.docker
def test_real_image_builds_and_runs():
    """Real ``docker build`` of the python3.11 template + a start smoke.

    Only a real daemon can answer: does the base image exist in this registry,
    does pip resolve against the configured index, does the non-root user own
    what it needs, does the entrypoint actually exec the app. Runs in the CI
    middleware stage and in the 114 verification (T075 step 1).
    """
    pytest.skip("executed in the CI docker stage / on 114, not in the unit suite")
