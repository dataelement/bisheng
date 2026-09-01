"""Startup self-heal: publish bundles an upgraded host still holds locally.

The rule under test is deliberately conservative. Several API replicas boot at
once, each with a different local disk; if any of them published whatever copy it
happened to have, the winner would be arbitrary — which is the very multi-node
inconsistency this migration exists to remove. So a bundle is published only when
this host can prove it matches what the row recorded, and everything else is
escalated to the operator by name.
"""

from __future__ import annotations

import pytest

from bisheng.linsight.domain.models.linsight_skill import (
    SKILL_SOURCE_BUILTIN,
    SKILL_SOURCE_MANUAL,
    LinsightSkill,
)
from bisheng.linsight.domain.services import skill_bundle_backfill as backfill
from bisheng.linsight.domain.services.skill_store import LEGACY_TENANT_SKILLS_DIR, SkillStore
from test.linsight.fixtures.fake_minio import FakeMinioStorage

TENANT = 1
SKILL_BODY = b"---\nname: demo-skill\ndescription: d\n---\n\nbody"


class _FakeDao:
    def __init__(self, rows):
        self.rows = rows
        self.updates = 0

    async def get_page(self, page=1, page_size=100):
        return list(self.rows), len(self.rows)

    async def update(self, skill):
        self.updates += 1
        return skill


def _row(name="demo-skill", *, size=len(SKILL_BODY), source=SKILL_SOURCE_MANUAL, content_hash=""):
    return LinsightSkill(
        id=1,
        tenant_id=TENANT,
        name=name,
        display_name=name,
        description="d",
        enabled=True,
        source=source,
        object_path="",
        content_hash=content_hash,
        size=size,
    )


def _write_legacy(root, tenant_id, name, body=SKILL_BODY):
    base = root / LEGACY_TENANT_SKILLS_DIR / str(tenant_id) / name
    base.mkdir(parents=True, exist_ok=True)
    (base / "SKILL.md").write_bytes(body)
    return base


@pytest.fixture
def env(tmp_path, monkeypatch):
    legacy_root = tmp_path / "legacy"

    class _Conf:
        skills_root = str(legacy_root)

    class _Settings:
        @staticmethod
        def get_linsight_conf():
            return _Conf()

    monkeypatch.setattr(backfill, "bisheng_settings", _Settings)
    store = SkillStore(root=tmp_path / "cache", minio=FakeMinioStorage())
    return legacy_root, store


async def test_publishes_a_bundle_this_host_holds(env, monkeypatch):
    legacy_root, store = env
    _write_legacy(legacy_root, TENANT, "demo-skill")
    row = _row()
    dao = _FakeDao([row])
    monkeypatch.setattr(backfill, "LinsightSkillDao", dao)

    stats = await backfill.backfill_skill_bundles_from_local_disk(store=store)

    assert stats["published"] == 1
    assert row.content_hash and row.object_path.endswith(f"{row.content_hash}.zip")
    assert store.read_bytes(TENANT, "demo-skill", row.content_hash, "SKILL.md") == SKILL_BODY


async def test_a_row_already_pointing_at_storage_is_untouched(env, monkeypatch):
    legacy_root, store = env
    _write_legacy(legacy_root, TENANT, "demo-skill")
    dao = _FakeDao([_row(content_hash="deadbeef")])
    monkeypatch.setattr(backfill, "LinsightSkillDao", dao)

    stats = await backfill.backfill_skill_bundles_from_local_disk(store=store)

    assert stats["published"] == 0 and dao.updates == 0


async def test_builtin_rows_are_left_to_the_seeder(env, monkeypatch):
    """The image is a better source than any single host's disk."""
    legacy_root, store = env
    _write_legacy(legacy_root, TENANT, "demo-skill")
    dao = _FakeDao([_row(source=SKILL_SOURCE_BUILTIN)])
    monkeypatch.setattr(backfill, "LinsightSkillDao", dao)

    stats = await backfill.backfill_skill_bundles_from_local_disk(store=store)

    assert (stats["published"], stats["skipped_builtin"]) == (0, 1)
    assert dao.updates == 0


async def test_a_local_copy_that_disagrees_with_the_row_is_not_published(env, monkeypatch):
    """Publishing a partial/stale copy would make an arbitrary guess durable."""
    legacy_root, store = env
    _write_legacy(legacy_root, TENANT, "demo-skill", body=b"truncated")
    dao = _FakeDao([_row(size=len(SKILL_BODY))])  # row remembers the full size
    monkeypatch.setattr(backfill, "LinsightSkillDao", dao)

    stats = await backfill.backfill_skill_bundles_from_local_disk(store=store)

    assert (stats["published"], stats["size_mismatch"]) == (0, 1)
    assert dao.updates == 0


async def test_a_bundle_held_by_another_host_is_reported_not_invented(env, monkeypatch):
    legacy_root, store = env  # nothing written locally
    dao = _FakeDao([_row()])
    monkeypatch.setattr(backfill, "LinsightSkillDao", dao)

    stats = await backfill.backfill_skill_bundles_from_local_disk(store=store)

    assert (stats["published"], stats["elsewhere"]) == (0, 1)
    assert dao.updates == 0
