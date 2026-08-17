"""Startup self-heal for skill bundles still sitting on this host's local disk.

Before bundles moved to object storage, ``SKILLS_ROOT`` was authoritative — so an
upgraded deployment has rows whose ``content_hash`` is empty and whose bytes exist
only on whichever host wrote them. Those skills silently fail to load until the
bundle is published.

This is deliberately **narrow**, and does far less than the operational script
(``scripts/migrate_skills_to_object_storage.py``):

* it only publishes a bundle this host actually holds, whose byte count matches
  what the row recorded — a partial or stale local copy is left alone rather than
  becoming the version everyone gets;
* it never touches ``source='builtin'`` rows: those are republished from the
  image by the seeder, which is a better source than any host's disk;
* anything it cannot resolve is logged **by name**, because that is the operator's
  signal to run the script on the host that does hold it.

Why not do the whole migration here: several API replicas boot at once, each
seeing a different local disk. Letting whichever replica wins publish its copy is
exactly the multi-node inconsistency this change exists to remove. The narrow rule
above is safe under concurrency — every replica that acts publishes byte-identical
content — while anything ambiguous is escalated to a human instead of guessed.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
from bisheng.linsight.domain.models.linsight_skill import SKILL_SOURCE_BUILTIN, LinsightSkillDao
from bisheng.linsight.domain.services.skill_store import LEGACY_TENANT_SKILLS_DIR, SKILL_MD, SkillStore

_SKIP_PARTS = {"__pycache__", ".git"}
_SKIP_NAMES = {".DS_Store"}


def read_legacy_bundle(legacy_root: Path, tenant_id: int, name: str) -> dict[str, bytes] | None:
    """Read a bundle from the pre-object-storage on-disk layout, or None if absent."""
    base = legacy_root / LEGACY_TENANT_SKILLS_DIR / str(tenant_id) / name
    if not (base / SKILL_MD).is_file():
        return None
    files: dict[str, bytes] = {}
    for path in sorted(base.rglob("*")):
        if path.is_dir() or path.name in _SKIP_NAMES or _SKIP_PARTS & set(path.parts):
            continue
        files[path.relative_to(base).as_posix()] = path.read_bytes()
    return files or None


async def backfill_skill_bundles_from_local_disk(*, store: SkillStore | None = None) -> dict:
    """Publish what this host can prove it holds; name what it cannot. Returns counts."""
    store = store or SkillStore()
    legacy_root = Path(bisheng_settings.get_linsight_conf().skills_root).resolve()

    with bypass_tenant_filter():
        rows, _ = await LinsightSkillDao.get_page(page=1, page_size=100000)

    stats = {"published": 0, "skipped_builtin": 0, "size_mismatch": 0, "elsewhere": 0}
    unresolved: list[str] = []
    for row in rows:
        if row.content_hash:
            continue
        if row.source == SKILL_SOURCE_BUILTIN:
            stats["skipped_builtin"] += 1
            continue

        files = read_legacy_bundle(legacy_root, row.tenant_id, row.name)
        if files is None:
            stats["elsewhere"] += 1
            unresolved.append(f"{row.tenant_id}/{row.name}")
            continue
        if sum(len(c) for c in files.values()) != (row.size or 0):
            # Local copy disagrees with what the row recorded — could be a partial
            # write or an older revision. Publishing it would make a guess durable.
            stats["size_mismatch"] += 1
            unresolved.append(f"{row.tenant_id}/{row.name}")
            continue

        token = set_current_tenant_id(row.tenant_id)
        try:
            ref = store.write_bundle(row.tenant_id, row.name, files)
            row.object_path, row.content_hash, row.size = ref.object_key, ref.content_hash, ref.size
            await LinsightSkillDao.update(row)
            stats["published"] += 1
        except Exception:
            logger.exception("failed to publish local skill bundle {}/{}", row.tenant_id, row.name)
            unresolved.append(f"{row.tenant_id}/{row.name}")
        finally:
            current_tenant_id.reset(token)

    if unresolved:
        # Loud on purpose: these skills do not work until someone runs the
        # migration script on the host holding their bundle.
        logger.warning(
            "{} skill bundle(s) are not on object storage and not on this host — run "
            "scripts/migrate_skills_to_object_storage.py on the other API hosts: {}",
            len(unresolved),
            unresolved,
        )
    if any(stats.values()):
        logger.info("skill bundle backfill: {}", stats)
    return stats
