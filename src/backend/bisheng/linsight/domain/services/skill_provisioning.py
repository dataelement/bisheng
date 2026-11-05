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
        selected: skill names the user picked for this run. Not a copy filter any
            more: every enabled skill is copied. Kept for the log line; the picked
            names are highlighted in the prompt by SkillSelectionMiddleware.
        store: skill bundle store (injectable for tests).

    Returns:
        ``SkillProvisionResult(copied, failed)``. ``copied`` gates attaching the
        skills middleware. ``failed`` lists every skill that did not land; only the
        ones the user picked are surfaced (``user_visible_failures``).
    """
    store = store or SkillStore()
    # Governance gate, scoped to the current tenant (LinsightSkillDao.list_enabled
    # uses strict_tenant_filter); the worker has already restored tenant context.
    # Keep the whole row: it carries the content_hash that locates the bundle,
    # so resolving one costs no extra query.
    enabled_skills = await LinsightSkillDao.list_enabled()
    enabled = {skill.name: skill for skill in enabled_skills}
    # cofco 2026-11-05 (user decision): every governance-enabled skill of the tenant
    # is mounted on every run, as the release line does since F076 ("mount every
    # candidate"). The picker no longer gates the copy: ``selected`` only marks the
    # rows the model should prefer (SkillSelectionMiddleware) and decides which copy
    # failures reach the user (user_visible_failures). Governance still gates:
    # a disabled skill is never copied. F047 frontend-hidden skills are included as before.
    wanted = sorted(enabled)
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


def user_visible_failures(result: SkillProvisionResult, selected: list[str] | None) -> list[str]:
    """Copy failures worth a timeline row: only skills the user picked.

    Every enabled skill is mounted now, so an unpicked one that fails to copy is
    a log line, not a broken promise to the user.
    """
    picked = set(selected or [])
    return [name for name in result.failed if name in picked]
