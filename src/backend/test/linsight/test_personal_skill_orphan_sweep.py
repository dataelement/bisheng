"""Orphan personal skill objects are deleted per tenant.

A hash still named by a skill row stays. ``linsight/skills/`` is never part of
the sweep, and a child task only removes keys under its own tenant prefix.
"""

from bisheng.core.config.settings import CeleryConf
from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id
from bisheng.worker.linsight import personal_skill_sweep as sweep

LIVE = "a" * 64
ORPHAN = "b" * 64
OTHER = "c" * 64


def _key(tenant: int, user: int, name: str, digest: str) -> str:
    return f"linsight/personal-skills/{tenant}/{user}/{name}/{digest}.zip"


def test_unreferenced_hash_is_removed_and_a_live_hash_stays():
    names = [
        _key(3, 12, "pdf", ORPHAN),
        _key(3, 12, "pdf", LIVE),
        _key(9, 12, "pdf", OTHER),
        f"linsight/skills/3/pdf/{ORPHAN}.zip",
        _key(3, 12, "pdf", "not-a-hash"),
    ]
    doomed = sweep.orphan_object_keys(names, 3, {LIVE})
    assert doomed == [_key(3, 12, "pdf", ORPHAN)]


async def test_sweep_deletes_only_this_tenants_orphans():
    names = [
        _key(3, 12, "pdf", ORPHAN),
        _key(3, 12, "pdf", LIVE),
        _key(9, 12, "pdf", OTHER),
        f"linsight/skills/3/pdf/{ORPHAN}.zip",
    ]
    removed = []
    token = set_current_tenant_id(3)
    try:
        result = await sweep.run_sweep(
            3,
            list_objects=lambda tenant_id: names,
            live_hashes=lambda: {LIVE},
            remove=removed.append,
        )
    finally:
        current_tenant_id.reset(token)
    assert result == [_key(3, 12, "pdf", ORPHAN)]
    assert removed == result


async def test_a_mismatched_tenant_context_deletes_nothing():
    removed = []
    token = set_current_tenant_id(1)
    try:
        result = await sweep.run_sweep(
            3,
            list_objects=lambda tenant_id: [_key(3, 12, "pdf", ORPHAN)],
            live_hashes=lambda: set(),
            remove=removed.append,
        )
    finally:
        current_tenant_id.reset(token)
    assert result == []
    assert removed == []


async def test_a_delete_failure_is_logged_and_the_rest_continues(monkeypatch):
    logged = []
    monkeypatch.setattr(sweep.logger, "exception", lambda *args, **kwargs: logged.append(args))
    first = _key(3, 12, "pdf", ORPHAN)
    second = _key(3, 8, "sheet", OTHER)

    def remove(key):
        if key == first:
            raise RuntimeError("minio down")

    token = set_current_tenant_id(3)
    try:
        result = await sweep.run_sweep(
            3,
            list_objects=lambda tenant_id: [first, second],
            live_hashes=lambda: set(),
            remove=remove,
        )
    finally:
        current_tenant_id.reset(token)
    assert result == [second]
    assert logged


def test_dispatch_publishes_one_child_per_tenant_and_restores_the_caller():
    published = []

    def publish(tenant_id):
        published.append((tenant_id, get_current_tenant_id()))

    token = set_current_tenant_id(1)
    try:
        sweep.publish_tenant_sweeps([3, 9], publish)
        assert get_current_tenant_id() == 1
    finally:
        current_tenant_id.reset(token)
    assert published == [(3, 3), (9, 9)]
    assert get_current_tenant_id() != 9


async def test_dispatch_task_sends_the_tenant_header(monkeypatch):
    published = []

    async def tenants():
        return [3, 9]

    def apply_async(*, args, headers):
        published.append((args, headers, get_current_tenant_id()))

    monkeypatch.setattr(sweep, "_active_tenant_ids", tenants)
    monkeypatch.setattr(sweep.sweep_personal_skill_orphans, "apply_async", apply_async)
    token = set_current_tenant_id(1)
    try:
        await sweep._dispatch()
        assert get_current_tenant_id() == 1
    finally:
        current_tenant_id.reset(token)
    assert published == [
        ([3], {"tenant_id": 3}, 3),
        ([9], {"tenant_id": 9}, 9),
    ]


def test_sweep_task_logs_and_returns_when_the_run_fails(monkeypatch):
    logged = []

    async def boom(tenant_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(sweep, "run_sweep", boom)
    monkeypatch.setattr(sweep.logger, "exception", lambda *args, **kwargs: logged.append(args))
    assert sweep.sweep_personal_skill_orphans.run(3) == []
    assert logged


def test_default_beat_schedule_dispatches_the_sweep():
    entry = CeleryConf().beat_schedule["dispatch_personal_skill_orphan_sweep"]
    assert entry["task"] == "bisheng.worker.linsight.personal_skill_sweep.dispatch_personal_skill_orphan_sweep"
