"""Copy a run's selected skill bundles into the session workspace (F035, Fork X).

deepagents' ``SkillsMiddleware`` discovers a skill from the *directory* entries an
``ls`` returns (``is_dir=True``) and the model reads the body via the workspace
``read_file`` tool. Two facts make a naive wiring impossible:

  * the session ``WorkspaceBackend`` lists MinIO recursively and returns only
    *file* entries (``is_dir=False``) — deepagents' native ``skills=`` param
    pointed at it would discover zero skills;
  * skill bundles live in their own object-storage namespace the workspace
    ``read_file`` cannot reach.

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

import asyncio
from typing import NamedTuple

from loguru import logger

from bisheng.linsight.domain.models.linsight_skill import LinsightSkillDao
from bisheng.linsight.domain.services.skill_store import SkillStore

WORKSPACE_SKILLS_DIR = "skills"
"""Workspace subtree the copied bundles live under (``/skills/<name>/...``)."""


class SkillProvisionResult(NamedTuple):
    """Outcome of provisioning, split so the caller can tell silence from failure.

    ``failed`` holds skills the user explicitly picked and governance allowed, but
    which could not be loaded. That case used to be indistinguishable from "no
    skills requested" — a warning in the log and a task that ran on, quietly
    missing the capability the user asked for. It is now reported to the user.
    """

    copied: list[str]
    failed: list[str]


def _collect_bundle_pairs(store: SkillStore, tenant_id: int, name: str, content_hash: str) -> list[tuple[str, bytes]]:
    """Read a bundle's files as ``(workspace_path, bytes)`` upload pairs.

    Blocking I/O: the first call for a given version fetches the object, later
    ones are served from the node's local cache.
    """
    return [
        (
            f"/{WORKSPACE_SKILLS_DIR}/{name}/{entry['path']}",
            store.read_bytes(tenant_id, name, content_hash, entry["path"]),
        )
        for entry in store.list_files(tenant_id, name, content_hash)
    ]


async def materialize_session_skills(
    backend,
    tenant_id: int,
    selected: list[str] | None,
    store: SkillStore | None = None,
) -> SkillProvisionResult:
    """Copy allowed skill bundles into the workspace ``/skills/`` subtree.

    Args:
        backend: the session ``WorkspaceBackend`` (write-throughs to MinIO+cache).
        tenant_id: owning tenant; scopes the bundle object keys.
        selected: skill names picked for this run. Both ``None`` (field absent —
            a legacy row, or any client/caller that never sent it) and ``[]`` (the
            UI explicitly cleared the picker) mean "no skills this run": copy
            nothing. Only an explicit non-empty list opts in, and each name is
            still intersected with the tenant's governance-enabled set.
        store: skill bundle store (injectable for tests).

    Returns:
        ``SkillProvisionResult(copied, failed)``. ``copied`` gates attaching the
        skills middleware; a non-empty ``failed`` means the run is missing a
        capability the user explicitly asked for and must be surfaced.
    """
    store = store or SkillStore()
    # Governance gate, scoped to the current tenant (LinsightSkillDao.list_enabled
    # uses strict_tenant_filter); the worker has already restored tenant context.
    # Keep the whole row: it carries the content_hash that locates the bundle,
    # so resolving one costs no extra query.
    enabled_skills = await LinsightSkillDao.list_enabled()
    enabled = {skill.name: skill for skill in enabled_skills}
    # F047: frontend-hidden (and enabled) skills are internal capabilities — the
    # server force-includes them in EVERY run, even when the user selected
    # nothing. A disabled skill never dispatches, hidden or not (AC-09).
    hidden_forced = {skill.name for skill in enabled_skills if getattr(skill, "frontend_hidden", False)}

    # User-picked skills stay strictly opt-in: None ≡ [] ≡ "none picked this
    # run". Treating a missing field as "copy every enabled skill" was a footgun
    # (a stale/cached client or non-UI caller silently loaded everything). Only
    # the F047 forced set is added on top of the explicit selection.
    wanted = ({name for name in selected if name in enabled} if selected else set()) | hidden_forced
    if not wanted:
        return SkillProvisionResult([], [])

    copied: list[str] = []
    failed: list[str] = []
    for name in wanted:
        try:
            # Reading a bundle is blocking I/O (a cache miss also fetches the
            # object) — keep it off the worker's event loop so concurrent tasks
            # aren't stalled.
            pairs = await asyncio.to_thread(_collect_bundle_pairs, store, tenant_id, name, enabled[name].content_hash)
            if not pairs:
                logger.warning("linsight skill {!r} (tenant {}) resolved to an empty bundle", name, tenant_id)
                failed.append(name)
                continue
            responses = await backend.aupload_files(pairs)
            upload_errors = [r for r in responses if getattr(r, "error", None)]
            if upload_errors:
                logger.warning("linsight skill {!r} copy had failures, not advertising: {}", name, upload_errors)
                failed.append(name)
                continue
            copied.append(name)
        except Exception:
            # One broken bundle must never abort the task — but it must not be
            # invisible either: the user picked this skill and will not get it.
            logger.exception("failed to materialize linsight skill {!r} (tenant {})", name, tenant_id)
            failed.append(name)
    # loguru formats with str.format, NOT printf — printf placeholders print
    # literally and silently drop every arg (this line used to log a useless
    # "tenant=%s selected=%r ... -> materialized %s", hiding exactly the fact a
    # skill-provisioning investigation needs).
    logger.info(
        "linsight skill provisioning: tenant={} selected={!r} enabled={} -> materialized {} failed {}",
        tenant_id,
        selected,
        sorted(enabled),
        copied,
        failed,
    )
    return SkillProvisionResult(copied, failed)
