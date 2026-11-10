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

Calls that omit ``user_id`` keep the Fork X whitelist: only
``enabled (DB governance) ∩ selected (this run)`` bundles are materialized.
Calls that pass ``user_id`` copy every current task candidate (an enabled
personal skill covers a same-named tenant skill). The session ``skills`` column
still lists only what the user checked; that highlight is applied later and is
not written into ``SKILL.md``.
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

    ``snapshot`` records which skill row owns each directory copied into this
    session (name, skill id, owner, content hash). ``selected_names`` is set
    only when the request carried skill ids; the caller writes that list into
    the session ``skills`` column. ``None`` means the column already holds the
    names from a name-only request and must be left as they were.
    """

    copied: list[str]
    failed: list[str]
    snapshot: list[dict] | None = None
    selected_names: list[str] | None = None


# Submit stashes chosen ids here until the first provision resolves them to
# directory names. A real snapshot entry always has ``name`` and ``skill_id``.
PENDING_SKILL_IDS = "pending_skill_ids"


def pending_skill_snapshot(skill_ids: list[int] | None) -> list[dict] | None:
    """Marker stored on the session until provisioning resolves the ids."""
    if not skill_ids:
        return None
    return [{PENDING_SKILL_IDS: [int(skill_id) for skill_id in skill_ids]}]


def _split_snapshot(
    skill_snapshot: list[dict] | None, skill_ids: list[int] | None
) -> tuple[list[int] | None, list[dict]]:
    """Separate a pending id marker from directory-ownership entries."""
    if (
        skill_snapshot
        and len(skill_snapshot) == 1
        and isinstance(skill_snapshot[0], dict)
        and PENDING_SKILL_IDS in skill_snapshot[0]
        and "name" not in skill_snapshot[0]
    ):
        pending = skill_ids if skill_ids is not None else list(skill_snapshot[0][PENDING_SKILL_IDS])
        return pending, []
    prior = [
        entry
        for entry in (skill_snapshot or [])
        if isinstance(entry, dict) and entry.get("name") and "skill_id" in entry
    ]
    return skill_ids, prior


def _collect_bundle_pairs(
    store: SkillStore, tenant_id: int, name: str, content_hash: str, *, owner_user_id: int = 0
) -> list[tuple[str, bytes]]:
    """Read a bundle's files as ``(workspace_path, bytes)`` upload pairs.

    Blocking I/O: the first call for a given version fetches the object, later
    ones are served from the node's local cache. ``owner_user_id`` selects the
    personal-skill object prefix; 0 is the tenant skill prefix.
    """
    return [
        (
            f"/{WORKSPACE_SKILLS_DIR}/{name}/{entry['path']}",
            store.read_bytes(tenant_id, name, content_hash, entry["path"], owner_user_id=owner_user_id),
        )
        for entry in store.list_files(tenant_id, name, content_hash, owner_user_id=owner_user_id)
    ]


def _snapshot_entry(skill) -> dict:
    return {
        "name": skill.name,
        "skill_id": int(skill.id),
        "owner_user_id": int(skill.owner_user_id or 0),
        "content_hash": skill.content_hash,
    }


def _resolve_selected_directories(rows, candidates, skill_ids: list[int]) -> list[str]:
    """Map chosen ids onto the directory names that were actually copied.

    A checked tenant skill that shares its name with an enabled personal skill
    resolves to that personal skill's directory. The two rows share the name,
    so the column stores the directory the copy left behind.
    """
    by_id = {int(row.id): row for row in rows if row.id is not None}
    kept = {row.name for row in candidates}
    names: list[str] = []
    seen: set[str] = set()
    for skill_id in skill_ids:
        row = by_id.get(int(skill_id))
        if row is None or row.name not in kept or row.name in seen:
            continue
        seen.add(row.name)
        names.append(row.name)
    return names


class SkillsUnavailableForRunError(Exception):
    """F073: an unattended (Open API) run must not start without a picked skill."""

    def __init__(self, names: list[str]):
        self.names = list(names)
        super().__init__(f"Selected skills are unavailable: {', '.join(self.names)}")


async def materialize_session_skills(
    backend,
    tenant_id: int,
    selected: list[str] | None,
    store: SkillStore | None = None,
    *,
    strict: bool = False,
    user_id: int | None = None,
    skill_ids: list[int] | None = None,
    skill_snapshot: list[dict] | None = None,
    session=None,
) -> SkillProvisionResult:
    """Copy skill bundles into the workspace ``/skills/`` subtree.

    Args:
        backend: the session ``WorkspaceBackend`` (write-throughs to MinIO+cache).
        tenant_id: owning tenant; scopes the bundle object keys.
        selected: skill names picked for this run. With no ``user_id`` (the
            historical call), both ``None`` and ``[]`` copy nothing, and a
            non-empty list is intersected with governance-enabled tenant skills.
            With ``user_id``, every current task candidate is copied; ``selected``
            only records the highlight and the strict-run check.
        store: skill bundle store (injectable for tests).
        strict: F073 — for unattended runs. Any selected skill that is unknown,
            disabled or fails to copy raises ``SkillsUnavailableForRunError``.
        user_id: when set, copy ``list_candidates`` for this user and write the
            directory snapshot. Omitted calls keep the name-whitelist gate.
        skill_ids: ids chosen on this submit. Resolved to the directory names
            that the copy actually left, including a personal skill that covered
            a same-named tenant skill.
        skill_snapshot: directories already copied into this session. Those
            names are not written again, so a later candidate cannot mix its
            files into the same directory.
        session: when passed, ``skill_snapshot`` is written onto it. ``skills``
            is replaced only when ``skill_ids`` (or a pending-id marker) was set.

    Returns:
        ``SkillProvisionResult``. ``copied`` lists directories now in the
        session (newly written plus ones already in the snapshot) and gates the
        skills middleware.
    """
    if user_id is None:
        return await _materialize_selected(backend, tenant_id, selected, store, strict=strict)

    return await _materialize_candidates(
        backend,
        tenant_id,
        selected,
        store,
        strict=strict,
        user_id=user_id,
        skill_ids=skill_ids,
        skill_snapshot=skill_snapshot,
        session=session,
    )


async def _materialize_selected(
    backend,
    tenant_id: int,
    selected: list[str] | None,
    store: SkillStore | None,
    *,
    strict: bool,
) -> SkillProvisionResult:
    """Historical gate: governance-enabled ∩ explicitly selected names.

    ``None`` and ``[]`` copy nothing. Callers that pass ``user_id`` use
    ``_materialize_candidates`` instead.
    """
    if not selected:
        return SkillProvisionResult([], [])

    store = store or SkillStore()
    # Governance gate, scoped to the current tenant (LinsightSkillDao.list_enabled
    # uses strict_tenant_filter); the worker has already restored tenant context.
    # Keep the whole row: it carries the content_hash that locates the bundle, so
    # resolving one costs no extra query.
    enabled = {skill.name: skill for skill in await LinsightSkillDao.list_enabled()}
    wanted = sorted(name for name in selected if name in enabled)
    if strict:
        missing = [name for name in selected if name not in enabled]
        if missing:
            raise SkillsUnavailableForRunError(missing)
    if not wanted:
        return SkillProvisionResult([], [])

    copied: list[str] = []
    failed: list[str] = []
    for name in wanted:
        outcome = await _copy_one(backend, store, tenant_id, name, enabled[name].content_hash, owner_user_id=0)
        if outcome:
            copied.append(name)
        else:
            failed.append(name)
    logger.info(
        "linsight skill provisioning: tenant={} selected={!r} enabled={} -> materialized {} failed {}",
        tenant_id,
        selected,
        sorted(enabled),
        copied,
        failed,
    )
    if strict and failed:
        raise SkillsUnavailableForRunError(failed)
    return SkillProvisionResult(copied, failed)


async def _materialize_candidates(
    backend,
    tenant_id: int,
    selected: list[str] | None,
    store: SkillStore | None,
    *,
    strict: bool,
    user_id: int,
    skill_ids: list[int] | None,
    skill_snapshot: list[dict] | None,
    session,
) -> SkillProvisionResult:
    """Copy every current task candidate, skipping directories already snapshotted."""
    from bisheng.linsight.domain.services.personal_skill_service import PersonalSkillService

    store = store or SkillStore()
    pending_ids, prior = _split_snapshot(skill_snapshot, skill_ids)
    occupied = {entry["name"] for entry in prior}
    service = PersonalSkillService(store=store)
    candidates = await service.list_candidates(user_id)
    from bisheng.linsight.domain.services.user_skills import UserSkillsService

    candidates = [row for row, _ in await UserSkillsService(user_id).records(candidates=candidates)]
    if strict and selected:
        present = {row.name for row in candidates} | occupied
        missing = [name for name in selected if name not in present]
        if missing:
            raise SkillsUnavailableForRunError(missing)

    copied: list[str] = []
    failed: list[str] = []
    fresh: list[dict] = []
    for skill in sorted(candidates, key=lambda row: row.name):
        if skill.name in occupied:
            continue
        owner = int(skill.owner_user_id or 0)
        if await _copy_one(backend, store, tenant_id, skill.name, skill.content_hash, owner_user_id=owner):
            copied.append(skill.name)
            fresh.append(_snapshot_entry(skill))
        else:
            failed.append(skill.name)
    snapshot = [*prior, *fresh]
    # Directories already in the session still count as present: a resume that
    # skips the write must keep the skills middleware attached.
    present_names = [entry["name"] for entry in prior] + copied
    selected_names = None
    if pending_ids is not None:
        rows = await LinsightSkillDao.list_visible(user_id)
        selected_names = _resolve_selected_directories(rows, candidates, pending_ids)
    if session is not None:
        session.skill_snapshot = snapshot
        if selected_names is not None:
            session.skills = selected_names
    logger.info(
        "linsight skill provisioning: tenant={} user={} candidates={} kept={} -> materialized {} failed {}",
        tenant_id,
        user_id,
        sorted(skill.name for skill in candidates),
        sorted(occupied),
        copied,
        failed,
    )
    if strict and selected and any(name in failed for name in selected):
        raise SkillsUnavailableForRunError([name for name in selected if name in failed])
    return SkillProvisionResult(present_names, failed, snapshot, selected_names)


async def _copy_one(
    backend, store: SkillStore, tenant_id: int, name: str, content_hash: str, *, owner_user_id: int
) -> bool:
    """Copy one bundle. False means the caller should treat the name as failed."""
    try:
        pairs = await asyncio.to_thread(
            _collect_bundle_pairs, store, tenant_id, name, content_hash, owner_user_id=owner_user_id
        )
        if not pairs:
            logger.warning("linsight skill {!r} (tenant {}) resolved to an empty bundle", name, tenant_id)
            return False
        responses = await backend.aupload_files(pairs)
        upload_errors = [item for item in responses if getattr(item, "error", None)]
        if upload_errors:
            logger.warning("linsight skill {!r} copy had failures, not advertising: {}", name, upload_errors)
            return False
        return True
    except Exception:
        logger.exception("failed to materialize linsight skill {!r} (tenant {})", name, tenant_id)
        return False
