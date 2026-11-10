"""T094a — tier resolution: table wins, constant backs it up, changes apply at the next start (AC-63 / AC-64).

The contract these five cases pin (design D11 / T094):

* ``_resolve_tier`` reads the ``resource_tier`` row when there is one and
  falls back to F054's ``DEFAULT_TIERS`` when there is not — the two agree on
  a fresh deployment because F055 seeds the table from the constant.
* Limits are fixed **when the container is created**. Retuning a tier does
  not touch a running instance: no orchestrator ``deploy`` / update, no
  restart. The new spec is picked up by the next publish (a new deploy) or
  the next resume (a new deploy of the same version).
* The **AC-63 baseline is the spec resolved at that deploy**, i.e. what
  ``version.tier_id`` meant at the time — not what the table says now. A
  verifier that re-resolves the code after a retune would "find" a mismatch
  on an instance that is exactly as it was started.

The table is present but empty in this package's conftest on purpose (that is
the MVP reality before the first boot's seed); tests that need a row insert
one directly.
"""

from __future__ import annotations

import pytest

from bisheng.app_runtime.domain.constants import DEFAULT_TIER_ID, AppState, default_tier

pytestmark = pytest.mark.usefixtures("app_db", "fake_orchestrator", "fake_permission_projection")


def _constant_spec(code: str) -> dict:
    spec = default_tier(code)
    assert spec is not None
    return {"cpu": float(spec["cpu"]), "mem": int(spec["memory_mb"])}


async def _upsert_tier(app_db, code: str, *, cpu_millicores: int, memory_mb: int, enabled: bool = True) -> None:
    """Insert or retune the ``resource_tier`` row for ``code`` — what the admin tab (F055 T065) does."""
    from bisheng.database.models.resource_tier import ResourceTier, ResourceTierDao

    async with app_db() as session:
        existing = await ResourceTierDao.aget_by_code(session, code)
        if existing is None:
            await ResourceTierDao.acreate(
                session,
                ResourceTier(code=code, name=code, cpu_millicores=cpu_millicores, memory_mb=memory_mb, enabled=enabled),
            )
        else:
            await ResourceTierDao.aupdate_row(session, code, cpu_millicores=cpu_millicores, memory_mb=memory_mb)
        await session.commit()


def _deploy_tiers(fake_orchestrator) -> list[dict]:
    return [kwargs["tier"] for name, kwargs in fake_orchestrator.calls if name == "deploy"]


async def _stage_iteration(app_db, app_id: str, *, tier_id: str) -> str:
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService
    from bisheng.database.models.app_version import VERSION_KIND_ITERATION, AppVersion, AppVersionDao

    async with app_db() as session:
        row = AppVersion(
            app_id=app_id,
            version_no=2,
            kind=VERSION_KIND_ITERATION,
            code_object_key=f"apps/{app_id}/versions/v2/code.tar.gz",
            manifest={"port": 8080, "runtime": "python3.11"},
            capabilities={},
            injections={},
            tier_id=tier_id,
            runtime="python3.11",
        )
        await AppVersionDao.ainsert(session, row)
        await session.commit()
        version_id = row.id
    await AppStateService.stage_version(app_id, version_id)
    return version_id


async def test_tier_resolved_from_table_when_present_else_default_tiers(app_db):
    """AC-64 — the ``resource_tier`` row wins; without one, ``DEFAULT_TIERS`` answers (and unknown → default tier)."""
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    # Empty table (conftest): the constant, in runtime-manager's {cpu vCPU, mem MiB} shape.
    assert await AppStateService._resolve_tier("standard") == _constant_spec("standard")
    assert await AppStateService._resolve_tier(None) == _constant_spec(DEFAULT_TIER_ID)
    assert await AppStateService._resolve_tier("gigantic") == _constant_spec(DEFAULT_TIER_ID)

    # A row for the code — retuned away from the constant — takes over.
    await _upsert_tier(app_db, "standard", cpu_millicores=1500, memory_mb=3072)
    assert await AppStateService._resolve_tier("standard") == {"cpu": 1.5, "mem": 3072}
    # Other codes still fall back: the table is consulted per code, not all-or-nothing.
    assert await AppStateService._resolve_tier("light") == _constant_spec("light")

    # A retired row still resolves (AC-47): retirement blocks new selections upstream, not running specs.
    await _upsert_tier(app_db, "performance", cpu_millicores=4000, memory_mb=8192, enabled=False)
    assert await AppStateService._resolve_tier("performance") == {"cpu": 4.0, "mem": 8192}


async def test_tier_change_does_not_touch_running_instance(app_db, app_factory, app_owner, fake_orchestrator):
    """AC-64 — retuning the tier of a running app issues nothing: no deploy, no update, no restart."""
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService
    from bisheng.database.models.app import AppDao
    from bisheng.database.models.app_instance import AppInstanceDao

    await _upsert_tier(app_db, "standard", cpu_millicores=2000, memory_mb=4096)
    app, version = await app_factory(state=AppState.DRAFT.value, tier_id="standard")
    result = await AppStateService.publish(app.id, actor=app_owner.payload)
    assert result.ok and _deploy_tiers(fake_orchestrator) == [{"cpu": 2.0, "mem": 4096}]

    calls_before = list(fake_orchestrator.calls)
    async with app_db() as session:
        instance_before = await AppInstanceDao.aget_by_app(session, app.id)

    await _upsert_tier(app_db, "standard", cpu_millicores=500, memory_mb=1024)

    assert fake_orchestrator.calls == calls_before, "a tier change must not reach the orchestrator on its own"
    async with app_db() as session:
        app_row = await AppDao.aget(session, app.id)
        instance_after = await AppInstanceDao.aget_by_app(session, app.id)
    assert app_row.state == AppState.ONLINE.value and app_row.current_version_id == version.id
    assert (instance_after.phase, instance_after.exec_ref, instance_after.version_id) == (
        instance_before.phase,
        instance_before.exec_ref,
        instance_before.version_id,
    )


async def test_tier_change_takes_effect_on_next_publish(app_db, app_factory, app_owner, fake_orchestrator):
    """AC-64 — the next publish (a new container) is created with the retuned spec."""
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    await _upsert_tier(app_db, "standard", cpu_millicores=2000, memory_mb=4096)
    app, _first = await app_factory(state=AppState.DRAFT.value, tier_id="standard")
    await AppStateService.publish(app.id, actor=app_owner.payload)

    await _upsert_tier(app_db, "standard", cpu_millicores=1500, memory_mb=3072)
    # An iteration on the *same* tier code: the snapshot keeps the identifier,
    # the numbers are whatever the tier says at start time (F055 AC-48).
    second_id = await _stage_iteration(app_db, app.id, tier_id="standard")
    result = await AppStateService.publish(app.id, actor=app_owner.payload)

    assert result.ok and result.version_id == second_id
    assert _deploy_tiers(fake_orchestrator) == [{"cpu": 2.0, "mem": 4096}, {"cpu": 1.5, "mem": 3072}]


async def test_tier_change_takes_effect_on_resume(app_db, app_factory, app_owner, fake_orchestrator):
    """AC-64 — stop, retune, resume: the same version comes back with the new limits."""
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    await _upsert_tier(app_db, "standard", cpu_millicores=2000, memory_mb=4096)
    app, version = await app_factory(state=AppState.DRAFT.value, tier_id="standard")
    await AppStateService.publish(app.id, actor=app_owner.payload)
    await AppStateService.stop(app.id, actor=app_owner.payload)

    await _upsert_tier(app_db, "standard", cpu_millicores=1000, memory_mb=2048)
    result = await AppStateService.resume(app.id, actor=app_owner.payload)

    assert result.ok and result.version_id == version.id, "resume restarts the same frozen version"
    assert _deploy_tiers(fake_orchestrator) == [{"cpu": 2.0, "mem": 4096}, {"cpu": 1.0, "mem": 2048}]
    assert [name for name, _ in fake_orchestrator.calls] == ["admission", "deploy", "stop", "admission", "deploy"]


async def test_ac63_baseline_is_snapshot_tier_not_current_table(app_db, app_factory, app_owner, fake_orchestrator):
    """AC-63 (D11) — verifying an instance's limits uses the spec resolved at *its* deploy.

    After a retune the table and the running instance legitimately disagree.
    The instance is still exactly as started, so the number to check
    ``docker inspect`` against is the one that went into its ``deploy`` intent
    — re-resolving ``version.tier_id`` now would report a false mismatch.
    """
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService
    from bisheng.database.models.app_version import AppVersionDao

    await _upsert_tier(app_db, "standard", cpu_millicores=2000, memory_mb=4096)
    app, version = await app_factory(state=AppState.DRAFT.value, tier_id="standard")
    await AppStateService.publish(app.id, actor=app_owner.payload)

    deployed_tier = _deploy_tiers(fake_orchestrator)[0]
    async with app_db() as session:
        stored = await AppVersionDao.aget(session, app.id, version.id)
    assert stored.tier_id == "standard", "the snapshot freezes the identifier, not the numbers"
    assert deployed_tier == await AppStateService._resolve_tier(stored.tier_id) == {"cpu": 2.0, "mem": 4096}

    await _upsert_tier(app_db, "standard", cpu_millicores=500, memory_mb=1024)

    # The baseline for the running instance is unchanged; the current table is not it.
    assert _deploy_tiers(fake_orchestrator)[0] == deployed_tier == {"cpu": 2.0, "mem": 4096}
    assert await AppStateService._resolve_tier(stored.tier_id) == {"cpu": 0.5, "mem": 1024}
    assert await AppStateService._resolve_tier(stored.tier_id) != deployed_tier
