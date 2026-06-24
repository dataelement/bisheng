"""Copy a run's selected skill bundles into the session workspace (F035, Fork X).

deepagents' ``SkillsMiddleware`` discovers a skill from the *directory* entries an
``ls`` returns (``is_dir=True``) and the model reads the body via the workspace
``read_file`` tool. Two facts make a naive wiring impossible:

  * the session ``WorkspaceBackend`` lists MinIO recursively and returns only
    *file* entries (``is_dir=False``) — deepagents' native ``skills=`` param
    pointed at it would discover zero skills;
  * skill bundles live in a separate ``SKILLS_ROOT`` the workspace ``read_file``
    cannot reach.

So at task startup we copy the bundles this run is allowed to use into the
workspace ``/skills/`` subtree. ``WorkspaceBackend.aupload_files`` write-throughs
to both MinIO and the local cache, after which a plain ``SkillsMiddleware`` backed
by a ``FilesystemBackend`` over that cache can enumerate them (real on-disk dirs,
``is_dir``-aware) and the model reads the very same ``/skills/<name>/SKILL.md``
paths back through the workspace backend.

The copy IS the whitelist gate (Fork X): only ``enabled (DB governance) ∩
selected (this run)`` bundles are materialized, so the model physically cannot
see a skill it was not granted — no per-run config key, no runtime filter. This
replaces the dormant ``TenantSkillsMiddleware`` runtime whitelist.
"""

from __future__ import annotations

from loguru import logger

from bisheng.linsight.domain.models.linsight_skill import LinsightSkillDao
from bisheng.linsight.domain.services.skill_store import SkillStore

WORKSPACE_SKILLS_DIR = "skills"
"""Workspace subtree the copied bundles live under (``/skills/<name>/...``)."""


async def materialize_session_skills(
    backend,
    tenant_id: int,
    selected: list[str] | None,
    store: SkillStore | None = None,
) -> list[str]:
    """Copy allowed skill bundles into the workspace ``/skills/`` subtree.

    Args:
        backend: the session ``WorkspaceBackend`` (write-throughs to MinIO+cache).
        tenant_id: owning tenant; scopes the on-disk bundle source path.
        selected: skill names picked for this run. ``[]`` = none (all disabled);
            ``None`` = unconstrained (non-UI fallback — copy every enabled skill);
            ``["a", "b"]`` = exactly those that are also governance-enabled.
        store: skill disk store (injectable for tests).

    Returns:
        The skill names actually materialized. Empty when nothing matched — the
        caller then skips attaching the skills middleware entirely.
    """
    # [] = the UI explicitly disabled every skill for this run; copy nothing.
    if selected == []:
        return []

    store = store or SkillStore()
    # Governance gate, scoped to the current tenant (LinsightSkillDao.list_enabled
    # uses strict_tenant_filter); the worker has already restored tenant context.
    enabled = {skill.name for skill in await LinsightSkillDao.list_enabled()}
    wanted = enabled if selected is None else {name for name in selected if name in enabled}
    if not wanted:
        return []

    copied: list[str] = []
    for name in sorted(wanted):
        try:
            pairs = [
                (
                    f"/{WORKSPACE_SKILLS_DIR}/{name}/{entry['path']}",
                    store.read_bytes(tenant_id, name, entry["path"]),
                )
                for entry in store.list_files(tenant_id, name)
            ]
            if not pairs:
                logger.warning("linsight skill %r (tenant %s) has no files on disk; skipping", name, tenant_id)
                continue
            responses = await backend.aupload_files(pairs)
            failed = [r for r in responses if getattr(r, "error", None)]
            if failed:
                logger.warning("linsight skill %r copy had failures, not advertising: %s", name, failed)
                continue
            copied.append(name)
        except Exception:
            # Best-effort: one malformed/unreadable bundle must never abort the task.
            logger.exception("failed to materialize linsight skill %r (tenant %s)", name, tenant_id)
    logger.info(
        "linsight skill provisioning: tenant=%s selected=%r enabled=%s -> materialized %s",
        tenant_id,
        selected,
        sorted(enabled),
        copied,
    )
    return copied
