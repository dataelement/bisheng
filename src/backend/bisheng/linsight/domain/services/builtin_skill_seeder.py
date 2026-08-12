"""Install the kernel's built-in skill bundles into every tenant at startup.

A shipped skill has to reach the same place a user-uploaded one does — disk under
``SKILLS_ROOT/data/skills/{tenant_id}/<name>/`` plus a ``linsight_skill`` row —
because that is the only path the picker, the governance toggle and
``materialize_session_skills`` know about. Seeding there means an out-of-the-box
deployment shows the official skills with zero operator action, and every existing
capability (enable/disable, detail view, per-tenant isolation) works unchanged.

Why here and not in a migration: project law says an Alembic revision does DDL
only — any data seeding/backfill is a separate operational step. Doing it in the
API lifespan keeps `docker compose up` a single command while staying out of the
migration chain.

Idempotency is content-based: the bundle on disk is compared byte-for-byte with
the one shipped in the image, so an upgraded image updates the skill on the next
restart and an unchanged one costs a few file reads. A tenant that *edited* a
built-in skill has its row flipped to ``manual`` by the update endpoints, and
this seeder then leaves it alone forever — silently reverting a customer's edits
on upgrade would be far worse than letting their copy drift.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from loguru import logger

from bisheng.core.context.tenant import DEFAULT_TENANT_ID, current_tenant_id, set_current_tenant_id
from bisheng.database.models.tenant import TenantDao
from bisheng.linsight.domain.models.linsight_skill import (
    SKILL_SOURCE_BUILTIN,
    LinsightSkill,
    LinsightSkillDao,
)
from bisheng.linsight.domain.services.skill_store import (
    DISPLAY_NAME_META_KEY,
    SKILL_MD,
    SkillStore,
    parse_skill_md,
    validate_skill_name,
)

# ``bisheng/linsight/builtin_skills/<name>/`` — inside the package so every
# deployment shape (docker COPY, rsync, pip install) carries it automatically.
BUILTIN_SKILLS_DIR = Path(__file__).resolve().parents[2] / "builtin_skills"

_SKIP_PARTS = {"__pycache__", ".git"}
_SKIP_NAMES = {".DS_Store"}


def _read_bundle(bundle_dir: Path) -> tuple[dict, dict[str, bytes]] | None:
    """``(frontmatter, {relative_path: bytes})`` for one bundle dir, or None if unusable."""
    files: dict[str, bytes] = {}
    for path in sorted(bundle_dir.rglob("*")):
        if path.is_dir() or path.name in _SKIP_NAMES or _SKIP_PARTS & set(path.parts):
            continue
        files[path.relative_to(bundle_dir).as_posix()] = path.read_bytes()

    if SKILL_MD not in files:
        logger.warning("built-in skill {} has no {}; skipped", bundle_dir.name, SKILL_MD)
        return None
    try:
        meta, _ = parse_skill_md(files[SKILL_MD].decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        logger.warning("built-in skill {} has an unreadable {}: {}", bundle_dir.name, SKILL_MD, exc)
        return None

    name = str(meta.get("name") or "").strip()
    # The bundle directory name IS the skill id at runtime (deepagents resolves
    # skills by path), so a mismatch would install something the model cannot read.
    if name != bundle_dir.name or validate_skill_name(name) is not None:
        logger.warning(
            "built-in skill dir {!r} does not match a valid frontmatter name {!r}; skipped",
            bundle_dir.name,
            name,
        )
        return None
    if not str(meta.get("description") or "").strip():
        logger.warning("built-in skill {} has no description; skipped", name)
        return None
    return meta, files


def discover_builtin_bundles() -> dict[str, tuple[dict, dict[str, bytes]]]:
    """All shipped bundles, keyed by skill name."""
    if not BUILTIN_SKILLS_DIR.is_dir():
        return {}
    found: dict[str, tuple[dict, dict[str, bytes]]] = {}
    for child in sorted(BUILTIN_SKILLS_DIR.iterdir()):
        if not child.is_dir() or child.name in _SKIP_PARTS:
            continue
        parsed = _read_bundle(child)
        if parsed:
            found[child.name] = parsed
    return found


def _installed_matches(store: SkillStore, tenant_id: int, name: str, files: dict[str, bytes]) -> bool:
    """True when the on-disk bundle is byte-identical to the shipped one."""
    try:
        installed = {
            entry["path"]: store.read_bytes(tenant_id, name, entry["path"])
            for entry in store.list_files(tenant_id, name)
        }
    except Exception:  # missing dir, unreadable file — treat as "needs rewrite"
        return False
    return installed == files


def _display_name_of(meta: dict, name: str) -> str:
    metadata = meta.get("metadata")
    if isinstance(metadata, dict):
        value = str(metadata.get(DISPLAY_NAME_META_KEY) or "").strip()
        if value:
            return value
    return name


async def _seed_one(store: SkillStore, tenant_id: int, name: str, meta: dict, files: dict[str, bytes]) -> str:
    """Install/refresh one bundle for one tenant. Returns the outcome label."""
    existing = await LinsightSkillDao.get_by_name(name)

    if existing and existing.source != SKILL_SOURCE_BUILTIN:
        # The tenant forked it (any edit through the API flips source to manual).
        return "forked"
    if existing and _installed_matches(store, tenant_id, name, files):
        return "unchanged"

    size = store.write_bundle(tenant_id, name, files)
    display_name = _display_name_of(meta, name)
    description = str(meta["description"]).strip()

    if existing:
        existing.display_name = display_name
        existing.description = description
        existing.size = size
        existing.object_path = store.object_path(tenant_id, name)
        await LinsightSkillDao.update(existing)
        return "updated"

    try:
        await LinsightSkillDao.create(
            LinsightSkill(
                tenant_id=tenant_id,
                name=name,
                display_name=display_name,
                description=description,
                enabled=True,
                source=SKILL_SOURCE_BUILTIN,
                object_path=store.object_path(tenant_id, name),
                size=size,
            )
        )
        return "created"
    except Exception:
        # Several API replicas boot at once; uq_linsight_skill_tenant_name makes
        # the loser's INSERT fail, and the winner already wrote the same bytes.
        logger.debug("built-in skill {!r} insert lost a race for tenant {}", name, tenant_id)
        return "raced"


async def seed_builtin_skills(tenant_ids: Iterable[int] | None = None, *, store: SkillStore | None = None) -> dict:
    """Seed every shipped bundle into the given tenants (default: all active ones).

    Best-effort by contract: this runs inside application startup, so any failure
    is logged and swallowed — a broken bundle or an unreachable DB must never stop
    the service from coming up.
    """
    bundles = discover_builtin_bundles()
    if not bundles:
        return {}

    if tenant_ids is None:
        try:
            tenant_ids = await TenantDao.aget_active_ids()
        except Exception:
            logger.exception("built-in skill seeding could not list tenants; falling back to the default tenant")
            tenant_ids = set()
        # Single-tenant deployments have no rows in the tenant table at all.
        tenant_ids = tenant_ids or {DEFAULT_TENANT_ID}

    store = store or SkillStore()
    stats: dict[str, int] = {}
    for tenant_id in sorted(tenant_ids):
        token = set_current_tenant_id(tenant_id)
        try:
            for name, (meta, files) in bundles.items():
                try:
                    outcome = await _seed_one(store, tenant_id, name, meta, files)
                except Exception:
                    logger.exception("built-in skill {!r} failed to seed for tenant {}", name, tenant_id)
                    outcome = "failed"
                stats[outcome] = stats.get(outcome, 0) + 1
        finally:
            current_tenant_id.reset(token)

    changed = stats.get("created", 0) + stats.get("updated", 0)
    if changed:
        logger.info(
            "built-in skills seeded: {} bundle(s) x {} tenant(s) -> {}",
            len(bundles),
            len(list(tenant_ids)),
            stats,
        )
    else:
        logger.debug("built-in skills already up to date: {}", stats)
    return stats
