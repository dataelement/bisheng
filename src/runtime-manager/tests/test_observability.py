"""T097 — the four §7 events, asserted by **name and field set**, never by text.

The manager keeps no history: the desired-state file is the present tense, and
once a container is gone there is nothing left to inspect. These events are the
only record of what the manager did and why, so what is pinned here is the
payload a JSON handler would ship (``record.event`` / ``record.fields``) and
never the wording of a message.

The load-bearing case is
:meth:`TestAdmissionReject.test_admission_reject_carries_snapshot`: AC-65 shows
an owner "待上线（资源不足）" from the admission *response*, while an operator
reconciles capacity from this *log*. They have to be the same numbers, and the
only way to guarantee that is for both to come out of one payload — which is
what the assertion checks, field by field.
"""

from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException

from runtime_manager.admission import PURPOSE_BUILD, PURPOSE_RUN, AdmissionService, Tier
from runtime_manager.api.schemas import DeployRequest, HealthIn, TierIn
from runtime_manager.observability import (
    EVENT_ADMISSION_REJECT,
    EVENT_FIELDS,
    EVENT_INTENT,
    EVENT_REBUILD,
    EVENT_RECONCILE,
    intent_span,
)
from tests.fakes import FakeHostProbe


@pytest.fixture(autouse=True)
def _capture(caplog):
    caplog.set_level(logging.DEBUG, logger="runtime_manager")


@pytest.fixture()
def events(caplog):
    def _of(event: str) -> list[logging.LogRecord]:
        return [record for record in caplog.records if getattr(record, "event", None) == event]

    return _of


def _fields(record: logging.LogRecord) -> dict:
    return record.fields


def _assert_contract(record: logging.LogRecord, event: str) -> dict:
    fields = _fields(record)
    missing = set(EVENT_FIELDS[event]) - set(fields)
    assert not missing, f"{event} emitted without {sorted(missing)}"
    return fields


def _deploy_request(**overrides) -> DeployRequest:
    payload = {
        "app_id": "app-1",
        "slug": "sales-report",
        "version_id": "ver-0123456789abcdef",
        "version_no": 3,
        "image_ref": "bisheng-app/sales-report:3-ver-0123",
        "tier": TierIn(cpu=0.5, mem=512),
        "port": 8080,
        "health": HealthIn(path="/healthz"),
    }
    payload.update(overrides)
    return DeployRequest(**payload)


class TestIntentSpan:
    def test_intent_fields_complete_on_success(self, events):
        with intent_span("deploy", "app-1") as span:
            span.result = "running"

        fields = _assert_contract(events(EVENT_INTENT)[0], EVENT_INTENT)
        assert fields["kind"] == "deploy"
        assert fields["app_id"] == "app-1"
        assert fields["result"] == "running"
        assert fields["latency_ms"] >= 0.0

    def test_a_refused_intent_is_logged_with_its_machine_code(self, events):
        """A manager error is an outcome, not a disappearance.

        The code in the event is the same string the backend maps onto a 161xx —
        so "which intent was refused, and with what" is answerable from this
        host alone, without the caller's logs.
        """
        with pytest.raises(HTTPException):
            with intent_span("deploy", "app-1"):
                raise HTTPException(status_code=409, detail={"code": "capacity_exhausted", "message": "no room"})

        record = events(EVENT_INTENT)[0]
        assert _fields(record)["result"] == "capacity_exhausted"
        assert record.levelno == logging.WARNING, "a refusal an operator has to find must not be INFO"

    def test_an_unexpected_exception_still_closes_the_span(self, events):
        with pytest.raises(ValueError):
            with intent_span("stop", "app-2"):
                raise ValueError("boom")

        fields = _assert_contract(events(EVENT_INTENT)[0], EVENT_INTENT)
        assert fields["result"] == "error"

    def test_deploy_route_emits_the_intent_event(self, rtm_client, monkeypatch, events):
        """End to end through the real route, not just the helper."""
        monkeypatch.setattr(
            "runtime_manager.admission.LinuxHostProbe.snapshot",
            lambda self: FakeHostProbe().snapshot(),
        )
        monkeypatch.setattr("runtime_manager.probe.HttpxProbe.get", lambda self, url, timeout=2.0: 200)

        assert rtm_client.post("/v1/intents/deploy", _deploy_request().model_dump()).status_code == 200

        fields = _assert_contract(events(EVENT_INTENT)[-1], EVENT_INTENT)
        assert fields["kind"] == "deploy"
        assert fields["app_id"] == "app-1"
        assert fields["result"] == "running"


class TestAdmissionReject:
    def test_admission_reject_carries_snapshot(self, rtm_config, events):
        """The event and the response read the same numbers — see the module docstring."""
        service = AdmissionService(
            rtm_config,
            host_probe=FakeHostProbe(mem_available_mb=2100),
            store=_EmptyStore(),
        )

        result = service.evaluate(Tier(cpu=0.5, mem_mb=512), purpose=PURPOSE_RUN)
        assert result.admitted is False, "precondition: this is the refusal path"

        fields = _assert_contract(events(EVENT_ADMISSION_REJECT)[0], EVENT_ADMISSION_REJECT)
        assert fields["reason"] == result.reason
        assert fields["purpose"] == PURPOSE_RUN
        assert fields["required_mb"] == result.required_mb
        assert fields["required_cpu"] == result.required_cpu
        assert fields["snapshot"] == result.snapshot, "AC-65 copy and operator log must not diverge"

    def test_a_refused_build_says_so(self, rtm_config, events):
        """Builds go through the same door; the purpose is what tells them apart."""
        service = AdmissionService(rtm_config, host_probe=FakeHostProbe(mem_available_mb=2100), store=_EmptyStore())

        service.evaluate(None, purpose=PURPOSE_BUILD)

        assert _fields(events(EVENT_ADMISSION_REJECT)[0])["purpose"] == PURPOSE_BUILD

    def test_an_unreadable_host_is_also_a_logged_refusal(self, rtm_config, events):
        """Zeroed snapshot = "we could not read", not "the machine is full"."""
        service = AdmissionService(rtm_config, host_probe=_BlindProbe(), store=_EmptyStore())

        result = service.evaluate(Tier(cpu=0.5, mem_mb=512))

        fields = _assert_contract(events(EVENT_ADMISSION_REJECT)[0], EVENT_ADMISSION_REJECT)
        assert fields["reason"] == result.reason == "host_capacity_unreadable"
        assert fields["snapshot"]["total_mb"] == 0

    def test_an_admitted_request_logs_nothing(self, rtm_config, events):
        service = AdmissionService(rtm_config, host_probe=FakeHostProbe(), store=_EmptyStore())

        assert service.evaluate(Tier(cpu=0.5, mem_mb=512)).admitted is True
        assert events(EVENT_ADMISSION_REJECT) == [], "the quiet case must stay quiet"


class TestReconcileAndRebuild:
    def test_intent_and_reconcile_fields(self, rtm_config, fake_docker, events):
        """One pass, one event, with what it saw and what it did."""
        from tests.test_reconciler import _deploy, _reconciler

        _deploy(rtm_config, fake_docker)
        _reconciler(rtm_config, fake_docker).reconcile_once()

        fields = _assert_contract(events(EVENT_RECONCILE)[-1], EVENT_RECONCILE)
        assert fields["desired"] == 1
        assert fields["actual"] == 1
        assert set(fields["actions"]) >= {"recreated", "started", "rebuilt", "stopped", "reclaimed", "failures"}
        assert all(count == 0 for count in fields["actions"].values()), "a healthy pass acts on nothing"

    def test_a_pass_that_acted_counts_what_it_did(self, rtm_config, fake_docker, events):
        from tests.test_reconciler import _deploy, _reconciler

        name = _deploy(rtm_config, fake_docker)
        fake_docker.remove_container(name, force=True)

        _reconciler(rtm_config, fake_docker).reconcile_once()

        fields = _fields(events(EVENT_RECONCILE)[-1])
        assert fields["actions"]["recreated"] == 1

    def test_rebuild_is_its_own_warning(self, rtm_config, fake_docker, events):
        """§7: rebuild frequency is an application-health signal, so it cannot be
        buried inside the reconcile counters."""
        from tests.test_reconciler import _deploy, _reconciler

        name = _deploy(rtm_config, fake_docker)
        reconciler = _reconciler(rtm_config, fake_docker)
        fake_docker.set_health(name, "unhealthy")
        reconciler.reconcile_once()
        fake_docker.set_health(name, "unhealthy")
        reconciler.reconcile_once()

        records = events(EVENT_REBUILD)
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        fields = _assert_contract(records[0], EVENT_REBUILD)
        assert fields["app_id"] == "app-1"
        assert fields["reason"] == "unhealthy"
        assert fields["generation"] == 2, "a new execution body is a new generation (D5.1)"


class _EmptyStore:
    """Nothing committed yet — keeps gate ② out of the way of gate ① tests."""

    def committed(self) -> tuple[int, float]:
        return 0, 0.0


class _BlindProbe:
    def snapshot(self):
        from runtime_manager.admission import HostProbeUnavailable

        raise HostProbeUnavailable("cannot read /proc/meminfo: no such file")
