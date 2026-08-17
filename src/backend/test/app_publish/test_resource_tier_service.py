"""T014 — ``ResourceTierService``: seed, tier resolution, retirement, "no delete".

The four invariants this file exists to pin down:

* **One source of specs.** The seed reads F054's ``DEFAULT_TIERS`` (overridable
  by ``settings.app_runtime.default_tiers``), so "table not seeded yet" and
  "table just seeded" describe the same limits. A second literal copy anywhere
  makes ``docker inspect`` disagree with the admin page (design 坑 27).
* **A retired tier still resolves.** ``enabled=False`` blocks *new* selections
  only; a version that froze ``tier_id='light'`` years ago must still be able
  to look up its spec when it is restarted (AC-47). The two paths are therefore
  separate methods, not a boolean argument that a caller can forget.
* **One code, two reasons.** A tier failure is always ``16223``; whether it was
  missing or retired lives in ``data.reason``. Splitting it into two codes was
  tried upstream and produced a code with no writer (errcode module docstring).
* **No delete, ever.** F054 is allowed to assume "``tier_id`` always resolves",
  and that assumption is only true because the DAO offers no way to remove a
  row. The assertion is on the DAO's surface, not on a behaviour, because a
  behaviour test would pass the moment somebody adds the method and does not
  call it yet.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _service():
    from bisheng.app_publish.domain.services.resource_tier_service import ResourceTierService

    return ResourceTierService


# ---------------------------------------------------------------------------
# Seed (AC-44)
# ---------------------------------------------------------------------------


async def test_seed_creates_three_platform_level_tiers(publish_db, tier_seed):
    """轻量 1C/2G · 标准 2C/4G · 性能 4C/8G, shared across tenants (no ``tenant_id``)."""
    from bisheng.database.models.resource_tier import ResourceTier

    by_code = {tier.code: tier for tier in tier_seed}
    assert set(by_code) == {"light", "standard", "performance"}
    assert (by_code["light"].cpu_millicores, by_code["light"].memory_mb) == (1000, 2048)
    assert (by_code["standard"].cpu_millicores, by_code["standard"].memory_mb) == (2000, 4096)
    assert (by_code["performance"].cpu_millicores, by_code["performance"].memory_mb) == (4000, 8192)
    # Every tier ships plain-language guidance (AC-44) and a display order.
    assert all(tier.description for tier in tier_seed)
    assert [tier.code for tier in sorted(tier_seed, key=lambda row: row.sort_order)] == [
        "light",
        "standard",
        "performance",
    ]
    # Platform-level: the table has no tenant column at all, so nothing can
    # scope a tier to one tenant by accident.
    assert "tenant_id" not in ResourceTier.model_fields


async def test_seed_values_come_from_f054_default_tiers_constant(tier_seed):
    """The DB rows and the F054 constant describe the same three tiers (design D11 / 坑 27)."""
    from bisheng.app_runtime.domain.constants import DEFAULT_TIERS

    constant = {spec["tier_id"]: spec for spec in DEFAULT_TIERS}
    assert set(constant) == {row.code for row in tier_seed}
    for row in tier_seed:
        spec = constant[row.code]
        assert row.cpu_millicores == round(float(spec["cpu"]) * 1000)
        assert row.memory_mb == int(spec["memory_mb"])
        assert row.name == spec["name"]


async def test_settings_default_tiers_overrides_constant(publish_db, app_runtime_settings):
    """``settings.app_runtime.default_tiers`` wins — this is how 114 shrinks ``light`` (坑 27)."""
    from bisheng.database.models.resource_tier import ResourceTierDao

    service = await _service()
    app_runtime_settings(
        default_tiers={
            "light": {"name": "轻量", "cpu_millicores": 300, "memory_mb": 512, "description": "114 sized"},
            "standard": {"name": "标准", "cpu_millicores": 600, "memory_mb": 1024},
        }
    )
    await service.seed_resource_tiers()
    async with publish_db() as session:
        rows = {row.code: row for row in await ResourceTierDao.alist(session)}
    assert set(rows) == {"light", "standard"}, "an override replaces the tier set, it does not merge into it"
    assert (rows["light"].cpu_millicores, rows["light"].memory_mb) == (300, 512)


async def test_seed_idempotent_by_code_does_not_reset_admin_edits(publish_db, tier_seed):
    """Re-seeding neither duplicates rows nor undoes a super admin's retune (same judgement as AC-19)."""
    from bisheng.database.models.resource_tier import ResourceTierDao

    service = await _service()
    async with publish_db() as session:
        await ResourceTierDao.aupdate_row(session, "light", cpu_millicores=250, memory_mb=512)
        await session.commit()

    await service.seed_resource_tiers()

    async with publish_db() as session:
        rows = await ResourceTierDao.alist(session)
        light = await ResourceTierDao.aget_by_code(session, "light")
    assert len(rows) == 3, "seeding twice must not duplicate rows"
    assert (light.cpu_millicores, light.memory_mb) == (250, 512), "an upgrade must not reset a tuned tier"


# ---------------------------------------------------------------------------
# Tier resolution (AC-46 / AC-47)
# ---------------------------------------------------------------------------


async def test_manifest_without_tier_resolves_light(tier_seed):
    """No ``tier:`` in the manifest → 轻量 (AC-46)."""
    service = await _service()
    assert (await service.resolve_tier(None)).code == "light"


async def test_unknown_tier_rejected_16223_reason_not_found(tier_seed):
    from bisheng.common.errcode.app_publish import AppTierUnavailableError

    service = await _service()
    with pytest.raises(AppTierUnavailableError) as excinfo:
        await service.resolve_tier("gigantic")
    assert excinfo.value.code == 16223
    assert excinfo.value.kwargs["details"]["reason"] == "not_found"


async def test_disabled_tier_rejected_16223_reason_disabled(publish_db, tier_seed):
    """Same code as "not found" — the reason is a field, not a second code."""
    from bisheng.common.errcode.app_publish import AppTierUnavailableError
    from bisheng.database.models.resource_tier import ResourceTierDao

    service = await _service()
    async with publish_db() as session:
        await ResourceTierDao.aupdate_row(session, "performance", enabled=False)
        await session.commit()

    with pytest.raises(AppTierUnavailableError) as excinfo:
        await service.resolve_tier("performance")
    assert excinfo.value.code == 16223
    assert excinfo.value.kwargs["details"]["reason"] == "disabled"


async def test_disabled_tier_existing_apps_keep_running_and_resolve_spec(publish_db, tier_seed):
    """Retirement blocks *new* selections only; a frozen ``tier_id`` still resolves (AC-47)."""
    from bisheng.database.models.resource_tier import ResourceTierDao

    service = await _service()
    async with publish_db() as session:
        await ResourceTierDao.aupdate_row(session, "performance", enabled=False)
        await session.commit()

    spec = await service.resolve_spec("performance")
    assert (spec.cpu_millicores, spec.memory_mb) == (4000, 8192)
    assert spec.enabled is False
    # And it disappears from the selection list a new publish may choose from.
    assert "performance" not in {tier.code for tier in await service.list_tiers(enabled_only=True)}
    assert "performance" in {tier.code for tier in await service.list_tiers()}


async def test_dao_has_no_delete_method():
    """"``tier_id`` always resolves" is an invariant F054 relies on (AC-47 / design D11)."""
    from bisheng.app_publish.domain.services import resource_tier_service
    from bisheng.database.models.resource_tier import ResourceTierDao

    forbidden = [name for name in dir(ResourceTierDao) if "delete" in name.lower() or "remove" in name.lower()]
    assert forbidden == [], f"ResourceTierDao must not offer deletion: {forbidden}"
    service_forbidden = [
        name
        for name in dir(resource_tier_service.ResourceTierService)
        if "delete" in name.lower() or "remove" in name.lower()
    ]
    assert service_forbidden == []


# ---------------------------------------------------------------------------
# Snapshot semantics (AC-48)
# ---------------------------------------------------------------------------


async def test_tier_code_written_into_version_snapshot_spec_read_at_runtime(publish_db, tier_seed, app_factory):
    """The snapshot freezes the *code*; the spec is whatever the tier says today (AC-48)."""
    from bisheng.database.models.app_version import AppVersionDao
    from bisheng.database.models.resource_tier import ResourceTierDao

    service = await _service()
    app_row, version_row = await app_factory(tier_id="light")

    async with publish_db() as session:
        await ResourceTierDao.aupdate_row(session, "light", cpu_millicores=1500, memory_mb=3072)
        await session.commit()

    async with publish_db() as session:
        stored = await AppVersionDao.aget(session, app_row.id, version_row.id)
    assert stored.tier_id == "light", "the frozen snapshot keeps the identifier, not the numbers"
    spec = await service.resolve_spec(stored.tier_id)
    assert (spec.cpu_millicores, spec.memory_mb) == (1500, 3072), "limits follow the tier's current spec"


async def test_tier_in_use_app_count_counts_online_versions_only(publish_db, tier_seed, app_factory):
    """Counting rule for the deferred admin tab; ``DISTINCT app_id`` over online versions only."""
    service = await _service()
    await app_factory(tier_id="light", terminal_state="online")
    await app_factory(tier_id="light", terminal_state="online")
    await app_factory(tier_id="light", terminal_state="rejected")
    await app_factory(tier_id="standard", terminal_state="online")

    assert await service.count_apps_using("light") == 2
    assert await service.count_apps_using("standard") == 1
    assert await service.count_apps_using("performance") == 0
