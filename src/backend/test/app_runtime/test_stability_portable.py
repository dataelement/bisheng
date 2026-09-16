"""T095 — the stability acceptance, written so F059 can run it unchanged (AC-49).

AC-49 is a constraint on the *test*, not on the product: the AC-20 / AC-22 /
AC-46 / AC-47 / AC-48 / AC-50 cases must contain no step that only exists in the
single-host deployment form, so the k8s backend (F059) executes this same file
instead of writing a parallel suite that slowly drifts from this one.

Two rules keep that promise honest, and
:func:`test_ac49_no_form_specific_vocabulary` enforces the second mechanically:

* **Only the intent RPC and ``phase`` values.** Every observation goes through
  ``orchestrator_client`` (the facade INV-33 freezes) or through the app's
  ``state``. No execution-body handles, no host paths, no daemon calls.
* **The platform's own behaviour is what is asserted.** Recovery timing belongs
  to the runtime layer and is tested there (``runtime-manager`` /
  ``tests/test_reconciler.py``, whose real-orchestration half is marked and
  skipped without a host). What *this* file pins is that the platform stays out
  of the way: it does not re-issue intents, does not take a recovering
  application off the entry, and does not let one application's failure move
  another one.

The real-daemon half — killing a live instance, flipping a health endpoint to
500, restarting the runtime service under load — cannot run without an
orchestration host and is listed in the task's report as the 114 command set.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bisheng.app_runtime.domain.constants import ENTRY_VISIBLE_STATES, AppState
from bisheng.common.errcode.app_factory import AppOrchestratorUnavailableError

pytestmark = pytest.mark.usefixtures("app_db", "fake_orchestrator", "fake_permission_projection")

#: Phase vocabulary shared by both deployment forms (design §4.2 ①).
PHASE_RUNNING = "running"
PHASE_STARTING = "starting"
PHASE_UNHEALTHY = "unhealthy"

#: Words that would tie a case to one deployment form. The declaration itself
#: has to spell them, so each entry carries the exemption marker — the same
#: marker any future line may use, with a written reason next to it.
FORM_SPECIFIC_WORDS = (
    "docker",  # portable-vocab-ok: the vocabulary being banned
    "compose",  # portable-vocab-ok
    "container",  # portable-vocab-ok
    "kubectl",  # portable-vocab-ok
    "kubernetes",  # portable-vocab-ok
    "systemctl",  # portable-vocab-ok
    "nginx",  # portable-vocab-ok
    "/var/run",  # portable-vocab-ok
    "bind mount",  # portable-vocab-ok
)


async def _state(app_db, app_id) -> str:
    from bisheng.database.models.app import AppDao

    async with app_db() as session:
        row = await AppDao.aget(session, app_id)
    return row.state


def _intent_kinds(fake_orchestrator) -> list[str]:
    return [name for name, _ in fake_orchestrator.calls]


class TestSelfHealing:
    """AC-20 / AC-50 — recovery is the runtime layer's job, and only its job."""

    async def test_ac20_an_unhealthy_instance_does_not_move_the_application(
        self, app_db, app_factory, app_owner, fake_orchestrator
    ):
        """An application being repaired is still an online application.

        If the platform flipped it to ``stopped`` the moment a probe failed, a
        self-healing event would turn into an outage that needs a human to press
        「重新上线」 — which is exactly what AC-20 says must not be needed.
        """
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        fake_orchestrator.responses["status"] = {"instance_id": "inst-1", "phase": PHASE_UNHEALTHY, "health": "bad"}

        instance = await AppQueryService.get_instance(app.id, actor=app_owner.payload)

        assert instance["phase"] == PHASE_UNHEALTHY
        assert await _state(app_db, app.id) == AppState.ONLINE.value
        assert _intent_kinds(fake_orchestrator) == ["status"], "the platform must not try to repair it itself"

    async def test_ac20_recovery_is_visible_as_a_phase_change_alone(self, app_factory, app_owner, fake_orchestrator):
        """The only evidence the platform needs — and the only one k8s also has."""
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

        app, _ = await app_factory(state=AppState.ONLINE.value)

        fake_orchestrator.responses["status"] = {"instance_id": "inst-1", "phase": PHASE_UNHEALTHY}
        assert (await AppQueryService.get_instance(app.id, actor=app_owner.payload))["phase"] == PHASE_UNHEALTHY

        fake_orchestrator.responses["status"] = {"instance_id": "inst-2", "phase": PHASE_RUNNING}
        recovered = await AppQueryService.get_instance(app.id, actor=app_owner.payload)

        assert recovered["phase"] == PHASE_RUNNING
        assert _intent_kinds(fake_orchestrator) == ["status", "status"], "no intent was issued to make this happen"

    async def test_ac50_alignment_after_an_outage_needs_no_platform_action(
        self, app_db, app_factory, app_owner, fake_orchestrator
    ):
        """AC-50 — the runtime layer realigns itself; the platform only reads.

        The sequence is "unreachable, then running again", with nothing in
        between: the desired state lives in the runtime layer, so a platform that
        re-published on every outage would fight the alignment it is waiting for.
        """
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

        app, _ = await app_factory(state=AppState.ONLINE.value)

        fake_orchestrator.responses["status"] = AppOrchestratorUnavailableError()
        with pytest.raises(AppOrchestratorUnavailableError):
            await AppQueryService.get_instance(app.id, actor=app_owner.payload)

        fake_orchestrator.responses["status"] = {"instance_id": "inst-9", "phase": PHASE_RUNNING}
        assert (await AppQueryService.get_instance(app.id, actor=app_owner.payload))["phase"] == PHASE_RUNNING

        assert set(_intent_kinds(fake_orchestrator)) == {"status"}
        assert await _state(app_db, app.id) == AppState.ONLINE.value


class TestRuntimeLayerOutage:
    """AC-22 — a runtime service that is restarting must not look like a deletion."""

    async def test_ac22_an_unreachable_runtime_layer_is_its_own_answer(self, app_factory, app_owner, fake_orchestrator):
        """16121, never 16101.

        Collapsing the two would make every restart of the runtime service render
        the application as "deleted" on its detail page, which is the single most
        alarming way to report a 20-second blip.
        """
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService
        from bisheng.common.errcode.app_factory import AppNotFoundError

        app, _ = await app_factory(state=AppState.ONLINE.value)
        fake_orchestrator.responses["status"] = AppOrchestratorUnavailableError()

        with pytest.raises(AppOrchestratorUnavailableError) as excinfo:
            await AppQueryService.get_instance(app.id, actor=app_owner.payload)

        assert excinfo.value.code == 16121
        assert excinfo.value.code != AppNotFoundError().code

    async def test_ac22_an_outage_does_not_change_the_recorded_state(
        self, app_db, app_factory, app_owner, fake_orchestrator
    ):
        """Already-running applications keep serving, so the platform keeps
        describing them as running: the state column is not a health readout."""
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        fake_orchestrator.responses["status"] = AppOrchestratorUnavailableError()

        with pytest.raises(AppOrchestratorUnavailableError):
            await AppQueryService.get_instance(app.id, actor=app_owner.payload)

        assert await _state(app_db, app.id) == AppState.ONLINE.value


class TestIsolation:
    """AC-46 / AC-47 — one application's trouble stays inside that application."""

    async def test_ac46_a_failed_publish_leaves_every_other_application_alone(
        self, app_db, app_factory, app_owner, fake_orchestrator
    ):
        """The neighbour is the assertion. A platform-wide effect would show up
        as the second application failing too, or changing state."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService
        from bisheng.common.errcode.app_factory import AppProbeFailedError

        broken, _ = await app_factory(state=AppState.DRAFT.value)
        healthy, _ = await app_factory(state=AppState.DRAFT.value)

        fake_orchestrator.responses["deploy"] = AppProbeFailedError(msg="never became ready")
        failed = await AppStateService.publish(broken.id, actor=app_owner.payload)
        assert failed.ok is False

        fake_orchestrator.responses["deploy"] = {"instance_id": "inst-ok", "phase": PHASE_RUNNING}
        assert (await AppStateService.publish(healthy.id, actor=app_owner.payload)).ok is True

        assert await _state(app_db, healthy.id) == AppState.ONLINE.value
        assert await _state(app_db, broken.id) == AppState.PENDING_CAPACITY.value

    async def test_ac47_limits_are_declared_per_application(self, app_factory, app_owner, fake_orchestrator):
        """AC-47's "only that application is throttled" is expressed as a
        per-application ``tier`` on the deploy intent — the one input the runtime
        layer turns into limits, in either deployment form."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        light, _ = await app_factory(state=AppState.DRAFT.value, tier_id="light")
        standard, _ = await app_factory(state=AppState.DRAFT.value, tier_id="standard")

        await AppStateService.publish(light.id, actor=app_owner.payload)
        await AppStateService.publish(standard.id, actor=app_owner.payload)

        tiers = {kwargs["app_id"]: kwargs["tier"] for name, kwargs in fake_orchestrator.calls if name == "deploy"}
        assert tiers[light.id] != tiers[standard.id], "two applications, two independent budgets"
        assert set(tiers[light.id]) == {"cpu", "mem"}, "form-agnostic units, not a backend-specific spec"

    async def test_ac47_a_stop_touches_exactly_one_application(self, app_db, app_factory, app_owner, fake_orchestrator):
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        target, _ = await app_factory(state=AppState.ONLINE.value)
        bystander, _ = await app_factory(state=AppState.ONLINE.value)

        await AppStateService.stop(target.id, actor=app_owner.payload)

        stopped = [kwargs["app_id"] for name, kwargs in fake_orchestrator.calls if name == "stop"]
        assert stopped == [target.id]
        assert await _state(app_db, bystander.id) == AppState.ONLINE.value


class TestTransitionalWindow:
    """AC-48 — 「发布中」/「应用恢复中」 is a window, not an outage."""

    @pytest.mark.parametrize("phase", (PHASE_STARTING, PHASE_UNHEALTHY))
    async def test_ac48_a_transitional_instance_stays_on_the_entry(self, app_db, app_factory, app_owner, phase):
        """The retrying page only works while the application is still reachable
        through the entry; a state outside ``ENTRY_VISIBLE_STATES`` would answer
        「应用不存在或未上线」 and the automatic retry would never succeed."""
        from bisheng.database.models.app_instance import AppInstanceDao

        app, _ = await app_factory(state=AppState.ONLINE.value)
        async with app_db() as session:
            await AppInstanceDao.aupsert(session, app.id, phase=phase, tenant_id=app.tenant_id)
            await session.commit()

        assert AppState(await _state(app_db, app.id)) in ENTRY_VISIBLE_STATES

    async def test_ac48_a_deploy_that_is_still_starting_is_not_a_failure(
        self, app_db, app_factory, app_owner, fake_orchestrator
    ):
        """``starting`` comes back from a successful deploy intent (the readiness
        gate has passed for the platform's purposes); treating it as a failure
        would park an application that is seconds away from serving."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await app_factory(state=AppState.DRAFT.value)
        fake_orchestrator.responses["deploy"] = {"instance_id": "inst-1", "phase": PHASE_STARTING}

        result = await AppStateService.publish(app.id, actor=app_owner.payload)

        assert result.ok is True
        assert result.detail["phase"] == PHASE_STARTING
        assert await _state(app_db, app.id) == AppState.ONLINE.value


def test_ac49_no_form_specific_vocabulary():
    """The portability guard — AC-49 stated as a property of this file.

    A prose promise that "these cases are form agnostic" decays the first time
    somebody debugs a failure by reaching for the single-host tooling. Reading
    the file's own source is crude, and it is the only check that keeps working
    without a k8s environment to prove it against.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    offenders = [
        (number, line.strip())
        for number, line in enumerate(source.splitlines(), start=1)
        if "portable-vocab-ok" not in line and any(word in line.lower() for word in FORM_SPECIFIC_WORDS)
    ]
    assert not offenders, f"deployment-form specific vocabulary found: {offenders}"
