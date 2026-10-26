"""Capacity admission — D11 double gate (AC-19, AC-65).

The two gates exist because each one is independently falsifiable on real
hardware, and the tests below encode exactly those falsifications:

* Gate ① alone (``MemAvailable``) is falsified by starting N light apps in a
  row: none of them is resident yet, so every one of them passes and they OOM
  together later.
* Gate ② alone (sum of committed limits) is falsified by 114 itself, where
  ``MemAvailable`` sat around 0.9 GiB while the platform's own JVMs and workers
  held the memory — the quota arithmetic still said "plenty left" (K2).

So the verdict is the *conjunction*, and rejecting is a first-class answer:
"capacity exhausted" must never degrade into "start it anyway and see"
(spec §3 — no half-usable instances).
"""

from __future__ import annotations

import pytest

from runtime_manager.admission import AdmissionService, Tier
from runtime_manager.desired_state import InstanceRecord, get_store
from tests.fakes import FakeHostProbe

STANDARD = Tier(cpu=1.0, mem_mb=1024)
LIGHT = Tier(cpu=0.5, mem_mb=512)


def _service(config, probe: FakeHostProbe) -> AdmissionService:
    return AdmissionService(config, host_probe=probe)


def _record(app_id: str, mem_mb: int, cpu: float, phase: str) -> InstanceRecord:
    return InstanceRecord(
        app_id=app_id,
        slug=app_id,
        version_id=f"{app_id}-v1",
        version_no=1,
        image_ref=f"bisheng-app/{app_id}:1-abcdef12",
        tier_cpu=cpu,
        tier_mem_mb=mem_mb,
        port=8080,
        health_path="/healthz",
        container_name=f"bisheng-app-{app_id}-abcdef12",
        phase=phase,
    )


def test_gate1_pass_gate2_fail_rejects(rtm_config):
    """Plenty of free memory right now, but the committed limits are spent."""
    store = get_store(rtm_config)
    store.put(_record("heavy", mem_mb=26000, cpu=1.0, phase="running"))

    result = _service(rtm_config, FakeHostProbe(mem_available_mb=20480)).evaluate(STANDARD)

    assert result.admitted is False
    assert result.reason == "memory_quota_exhausted"
    # Gate ① genuinely passed — 20480 - 2048 reserve is far more than 1024.
    assert result.snapshot["mem_available_mb"] == 20480
    assert result.snapshot["committed_mb"] == 26000


def test_gate2_pass_gate1_fail_rejects(rtm_config):
    """The observed 114 shape: quota says fine, the machine says no (K2)."""
    store = get_store(rtm_config)
    store.put(_record("small", mem_mb=1024, cpu=0.5, phase="running"))

    result = _service(rtm_config, FakeHostProbe(mem_available_mb=900)).evaluate(STANDARD)

    assert result.admitted is False
    assert result.reason == "insufficient_available_memory"
    # Gate ② genuinely passed: 1024 committed + 1024 requested ≪ 32768 * 0.8.
    assert result.snapshot["committed_mb"] == 1024


def test_both_pass_admits(rtm_config):
    result = _service(rtm_config, FakeHostProbe()).evaluate(STANDARD)

    assert result.admitted is True
    assert result.reason == ""
    assert result.stage is None


def test_purpose_build_uses_build_reserve_mb(rtm_config):
    """A build is sized by ``build_reserve_mb``, not by the app's tier.

    Same host, same tier, two purposes, two verdicts — which is the only way to
    show the build path is not quietly reusing the tier number. The rejection
    carries ``stage="build_admission"`` so AC-15's "readable failure stage" and
    AC-19's capacity verdict are the same event seen from two sides.
    """
    probe = FakeHostProbe(mem_available_mb=4095)  # 4095 - 2048 reserve = 2047

    run_result = _service(rtm_config, probe).evaluate(LIGHT, purpose="run")
    build_result = _service(rtm_config, probe).evaluate(LIGHT, purpose="build")

    assert run_result.admitted is True
    assert build_result.admitted is False
    assert build_result.reason == "insufficient_available_memory"
    assert build_result.stage == "build_admission"
    assert build_result.required_mb == rtm_config.build_reserve_mb


def test_snapshot_fields_present(rtm_config):
    """AC-65 shows the operator *why*; AC-23 reuses the same numbers."""
    store = get_store(rtm_config)
    store.put(_record("a", mem_mb=1024, cpu=1.0, phase="running"))

    result = _service(rtm_config, FakeHostProbe()).evaluate(STANDARD)

    assert set(result.snapshot) >= {"mem_available_mb", "committed_mb", "total_mb", "cpu"}
    assert result.snapshot["total_mb"] == 32768
    assert result.snapshot["cpu"] == 8
    assert result.snapshot["committed_mb"] == 1024
    assert result.snapshot["committed_cpu"] == pytest.approx(1.0)


def test_cpu_gate_by_nproc_ratio(rtm_config):
    """CPU is gated the same way as memory: ``nproc × overcommit_ratio``."""
    store = get_store(rtm_config)
    store.put(_record("a", mem_mb=512, cpu=1.0, phase="running"))

    result = _service(rtm_config, FakeHostProbe(cpu_count=2)).evaluate(STANDARD)

    assert result.admitted is False
    assert result.reason == "cpu_quota_exhausted"


def test_single_instance_admission_counts_running_only(rtm_config):
    """Stopped apps hold no capacity — that is what makes resume re-check (AC-41)."""
    store = get_store(rtm_config)
    store.put(_record("alive", mem_mb=8192, cpu=1.0, phase="running"))
    store.put(_record("halted", mem_mb=8192, cpu=1.0, phase="stopped"))

    result = _service(rtm_config, FakeHostProbe()).evaluate(STANDARD)

    assert result.snapshot["committed_mb"] == 8192
    assert result.admitted is True


def test_admission_endpoint_returns_contract_shape(rtm_client, rtm_config, monkeypatch):
    """``POST /v1/admission`` — the backend's only capacity question (§4.2 ①)."""
    monkeypatch.setattr(
        "runtime_manager.admission.LinuxHostProbe.snapshot",
        lambda self: FakeHostProbe().snapshot(),
    )

    response = rtm_client.post(
        "/v1/admission", {"tier": {"cpu": 1.0, "mem": 1024}, "purpose": "run"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["admitted"] is True
    assert body["reason"] == ""
    assert set(body["snapshot"]) >= {"mem_available_mb", "committed_mb", "total_mb", "cpu"}


def test_admission_endpoint_rejects_unknown_purpose(rtm_client):
    response = rtm_client.post(
        "/v1/admission", {"tier": {"cpu": 1.0, "mem": 1024}, "purpose": "teleport"}
    )
    assert response.status_code == 422
