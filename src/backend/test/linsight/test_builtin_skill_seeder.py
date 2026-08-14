"""Built-in skills must reach every tenant on startup, without trampling edits.

The seeder is what makes `docker compose up` produce a deployment that already
has the official skills — no operator script, no manual zip upload. Its two
non-obvious contracts:

* idempotency is CONTENT-based, so an upgraded image refreshes the bundle on the
  next restart while an unchanged one is nearly free;
* a tenant that edited a built-in skill (row flipped to ``manual``) is never
  re-seeded — silently reverting a customer's edits on upgrade is worse than
  letting their copy drift.
"""

from __future__ import annotations

import shutil

import pytest

from bisheng.linsight.domain.models.linsight_skill import (
    SKILL_SOURCE_BUILTIN,
    SKILL_SOURCE_MANUAL,
    LinsightSkill,
)
from bisheng.linsight.domain.services import builtin_skill_seeder as seeder
from bisheng.linsight.domain.services.skill_store import SkillStore
from test.linsight.fixtures.fake_minio import FakeMinioStorage

SKILL_MD_TEMPLATE = """---
name: {name}
description: {description}
metadata:
  display-name: {display}
---

# {display}

正文。
"""


class _FakeDao:
    """In-memory stand-in; the seeder only needs get_by_name / create / update."""

    def __init__(self):
        self.rows: dict[tuple[int, str], LinsightSkill] = {}
        self.current_tenant = None
        self.creates = 0
        self.updates = 0

    async def get_by_name(self, name):
        from bisheng.core.context.tenant import current_tenant_id

        return self.rows.get((current_tenant_id.get(), name))

    async def create(self, skill):
        self.creates += 1
        skill.id = len(self.rows) + 1
        self.rows[(skill.tenant_id, skill.name)] = skill
        return skill

    async def update(self, skill):
        self.updates += 1
        self.rows[(skill.tenant_id, skill.name)] = skill
        return skill


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fake builtin dir + a real on-disk SkillStore + a fake DAO."""
    builtin = tmp_path / "builtin_skills"
    builtin.mkdir()
    monkeypatch.setattr(seeder, "BUILTIN_SKILLS_DIR", builtin)

    dao = _FakeDao()
    monkeypatch.setattr(seeder, "LinsightSkillDao", dao)

    store = SkillStore(root=tmp_path / "skills_root", minio=FakeMinioStorage())
    return builtin, store, dao


def _is_stored(store, dao, tenant_id, name) -> bool:
    """Bundle resolvable through the row's pointer — the way production reads it."""
    row = dao.rows.get((tenant_id, name))
    return bool(row) and store.exists(tenant_id, name, row.content_hash)


def _stored_bytes(store, dao, tenant_id, name, rel) -> bytes:
    return store.read_bytes(tenant_id, name, dao.rows[(tenant_id, name)].content_hash, rel)


def _write_bundle(builtin, name="demo-skill", description="演示技能描述", display="演示技能", extra=None):
    bundle = builtin / name
    (bundle / "scripts").mkdir(parents=True, exist_ok=True)
    (bundle / "SKILL.md").write_text(
        SKILL_MD_TEMPLATE.format(name=name, description=description, display=display), encoding="utf-8"
    )
    (bundle / "scripts" / "helper.py").write_text(extra or "print('v1')\n", encoding="utf-8")
    return bundle


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------
def test_discovery_reads_frontmatter_and_files(env):
    builtin, _store, _dao = env
    _write_bundle(builtin)

    found = seeder.discover_builtin_bundles()

    assert set(found) == {"demo-skill"}
    meta, files = found["demo-skill"]
    assert meta["name"] == "demo-skill"
    assert set(files) == {"SKILL.md", "scripts/helper.py"}


def test_discovery_skips_a_dir_whose_name_differs_from_frontmatter(env):
    """The directory name IS the runtime skill id, so a mismatch would install
    something the model cannot resolve."""
    builtin, _store, _dao = env
    bundle = _write_bundle(builtin, name="demo-skill")
    (bundle / "SKILL.md").write_text(
        SKILL_MD_TEMPLATE.format(name="something-else", description="d", display="x"), encoding="utf-8"
    )

    assert seeder.discover_builtin_bundles() == {}


def test_discovery_skips_a_dir_without_skill_md(env):
    builtin, _store, _dao = env
    (builtin / "not-a-skill").mkdir()
    (builtin / "not-a-skill" / "readme.txt").write_text("hi", encoding="utf-8")

    assert seeder.discover_builtin_bundles() == {}


def test_discovery_ignores_pycache(env):
    builtin, _store, _dao = env
    bundle = _write_bundle(builtin)
    cache = bundle / "scripts" / "__pycache__"
    cache.mkdir()
    (cache / "helper.cpython-311.pyc").write_bytes(b"\x00binary")

    _meta, files = seeder.discover_builtin_bundles()["demo-skill"]
    assert all("__pycache__" not in p for p in files)


# ---------------------------------------------------------------------------
# seeding
# ---------------------------------------------------------------------------
async def test_first_seed_creates_the_row_and_writes_the_bundle(env):
    builtin, store, dao = env
    _write_bundle(builtin)

    stats = await seeder.seed_builtin_skills([7], store=store)

    assert stats == {"created": 1}
    row = dao.rows[(7, "demo-skill")]
    assert row.source == SKILL_SOURCE_BUILTIN
    assert row.display_name == "演示技能"
    assert row.enabled is True
    assert _is_stored(store, dao, 7, "demo-skill")


async def test_second_run_is_a_noop_when_content_is_unchanged(env):
    builtin, store, dao = env
    _write_bundle(builtin)

    await seeder.seed_builtin_skills([7], store=store)
    stats = await seeder.seed_builtin_skills([7], store=store)

    assert stats == {"unchanged": 1}
    assert dao.updates == 0  # nothing rewritten


async def test_missing_object_is_republished_even_when_the_hash_matches(env):
    """Self-healing: comparing hashes alone would leave a deleted bundle broken forever.

    The byte-for-byte check this replaced repaired such a bundle on the next boot
    as a side effect; confirming the object still exists keeps that property
    without re-reading every file.
    """
    builtin, store, dao = env
    _write_bundle(builtin)
    await seeder.seed_builtin_skills([7], store=store)

    # The object disappears (bucket lifecycle, operator error) while the row keeps
    # advertising it, and no node has it cached.
    store.minio.store.clear()
    shutil.rmtree(store.root)

    stats = await seeder.seed_builtin_skills([7], store=store)

    assert stats == {"updated": 1}
    assert _is_stored(store, dao, 7, "demo-skill")


async def test_a_non_uniqueness_db_error_is_not_swallowed_as_a_race(env, monkeypatch):
    """Only the unique-key collision means "another replica won"."""
    builtin, store, dao = env
    _write_bundle(builtin)

    async def _boom(_skill):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(dao, "create", _boom)

    stats = await seeder.seed_builtin_skills([7], store=store)

    assert stats == {"failed": 1}  # not "raced"


async def test_changed_content_refreshes_the_bundle(env):
    """An upgraded image must update the installed skill on the next restart."""
    builtin, store, dao = env
    _write_bundle(builtin)
    await seeder.seed_builtin_skills([7], store=store)

    _write_bundle(builtin, description="改过的描述", extra="print('v2')\n")
    stats = await seeder.seed_builtin_skills([7], store=store)

    assert stats == {"updated": 1}
    assert dao.rows[(7, "demo-skill")].description == "改过的描述"
    assert _stored_bytes(store, dao, 7, "demo-skill", "scripts/helper.py") == b"print('v2')\n"


async def test_a_tenant_edit_opts_out_of_reseeding_forever(env):
    builtin, store, dao = env
    _write_bundle(builtin)
    await seeder.seed_builtin_skills([7], store=store)

    # The tenant edits it through the API -> SkillService._mark_forked, which also
    # repoints the row at the new version.
    edited = store.write_bundle(7, "demo-skill", {"SKILL.md": b"---\nname: demo-skill\ndescription: mine\n---\n\nmine"})
    row = dao.rows[(7, "demo-skill")]
    row.source = SKILL_SOURCE_MANUAL
    row.content_hash, row.object_path = edited.content_hash, edited.object_key

    _write_bundle(builtin, description="上游又改了", extra="print('v3')\n")
    stats = await seeder.seed_builtin_skills([7], store=store)

    assert stats == {"forked": 1}
    assert b"mine" in _stored_bytes(store, dao, 7, "demo-skill", "SKILL.md")


async def test_every_tenant_gets_its_own_copy(env):
    builtin, store, dao = env
    _write_bundle(builtin)

    stats = await seeder.seed_builtin_skills([1, 2, 3], store=store)

    assert stats == {"created": 3}
    assert all(_is_stored(store, dao, t, "demo-skill") for t in (1, 2, 3))


async def test_falls_back_to_the_default_tenant_when_none_are_active(env, monkeypatch):
    """Single-tenant deployments have no rows in the tenant table."""
    builtin, store, dao = env
    _write_bundle(builtin)

    class _NoTenants:
        @staticmethod
        async def aget_active_ids():
            return set()

    monkeypatch.setattr(seeder, "TenantDao", _NoTenants)

    stats = await seeder.seed_builtin_skills(store=store)

    assert stats == {"created": 1}
    assert _is_stored(store, dao, 1, "demo-skill")


async def test_one_broken_bundle_does_not_stop_the_others(env, monkeypatch):
    builtin, store, dao = env
    _write_bundle(builtin, name="good-skill", display="好技能")
    _write_bundle(builtin, name="bad-skill", display="坏技能")

    original = store.write_bundle

    def _explode(tenant_id, name, files):
        if name == "bad-skill":
            raise OSError("disk on fire")
        return original(tenant_id, name, files)

    monkeypatch.setattr(store, "write_bundle", _explode)

    stats = await seeder.seed_builtin_skills([7], store=store)

    assert stats == {"created": 1, "failed": 1}
    assert _is_stored(store, dao, 7, "good-skill")


async def test_tenant_context_is_restored_after_seeding(env):
    """Seeding runs inside per-tenant context; it must not leak into the caller's."""
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id

    builtin, store, dao = env
    _write_bundle(builtin)

    token = set_current_tenant_id(99)
    try:
        await seeder.seed_builtin_skills([1, 2], store=store)
        assert current_tenant_id.get() == 99
    finally:
        current_tenant_id.reset(token)


# ---------------------------------------------------------------------------
# the bundles actually shipped in this repo
# ---------------------------------------------------------------------------

# Deliberately a membership list, not a count: adding a fourth bundle later must
# not turn this guard red.
SHIPPED_BUNDLES = ("bisheng-pptx", "bisheng-xlsx", "bisheng-docx")


@pytest.mark.parametrize("name", SHIPPED_BUNDLES)
def test_the_shipped_bundle_is_valid(name):
    """Guards the real directory: every rule ``_read_bundle`` silently skips on
    (name mismatch, empty description, unparsable frontmatter) ships a skill that
    never installs and logs a warning nobody reads."""
    bundles = seeder.discover_builtin_bundles()

    assert name in bundles, f"{name} must ship with the backend package"
    meta, files = bundles[name]

    # The directory name IS the runtime skill id — deepagents resolves by path.
    assert meta["name"] == name

    description = str(meta.get("description") or "").strip()
    assert description, "an empty description makes the seeder skip the bundle"
    assert len(description) <= 1024, f"{name} description is {len(description)} chars"

    metadata = meta.get("metadata")
    assert isinstance(metadata, dict), f"{name} has no metadata mapping"
    assert str(metadata.get("display-name") or "").strip(), (
        f"{name} has no metadata.display-name — the picker would fall back to the raw slug"
    )

    assert "SKILL.md" in files
    assert any(p.startswith("scripts/") for p in files)


def test_no_shipped_bundle_is_silently_dropped():
    """A bundle dir that fails validation disappears from the mapping instead of
    raising, so compare directories on disk against what discovery returned."""
    on_disk = {p.name for p in seeder.BUILTIN_SKILLS_DIR.iterdir() if p.is_dir() and p.name != "__pycache__"}

    assert on_disk == set(seeder.discover_builtin_bundles()), (
        "a bundle directory exists but discover_builtin_bundles() rejected it"
    )
