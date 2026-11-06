"""Refuse the next read or code run when a copied skill was disabled or deleted.

The session snapshot says which skill row owns each directory. A same-named
tenant skill that is still enabled does not count: the files in the directory
belong to the snapshotted row. Paths the snapshot does not mention are left
alone. Content already returned to the model is not taken back.
"""

from __future__ import annotations

import re

SKILL_USE_REFUSAL = "技能“{name}”已停用或已删除，不能读取或执行它的文件。"

# A skill directory reference, not a file whose name merely starts with "skills".
_SKILL_DIR_IN_CODE = re.compile(r"(?<![A-Za-z0-9_-])skills[/\\]([a-z0-9]+(?:-[a-z0-9]+)*)[/\\]")


def skill_directory(rel_path: str) -> str | None:
    """Directory name under ``skills/``, or None when the path is elsewhere."""
    parts = (rel_path or "").replace("\\", "/").strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "skills" and parts[1]:
        return parts[1]
    return None


def skill_names_in_code(code: str) -> list[str]:
    """Skill directory names a script opens, in first-seen order."""
    found: list[str] = []
    for match in _SKILL_DIR_IN_CODE.finditer(code or ""):
        name = match.group(1)
        if name not in found:
            found.append(name)
    return found


def snapshot_entry(snapshot: list[dict] | None, name: str) -> dict | None:
    for entry in snapshot or []:
        if isinstance(entry, dict) and entry.get("name") == name and "skill_id" in entry:
            return entry
    return None


def refusal_for(name: str, snapshot: list[dict] | None, enabled: bool | None) -> str | None:
    """Refuse when the snapshotted row is disabled or gone.

    ``enabled is True`` means that row is still on. ``False`` is disabled,
    ``None`` is deleted. No snapshot entry means the path is not this session's
    skill copy.
    """
    if snapshot_entry(snapshot, name) is None:
        return None
    if enabled is True:
        return None
    return SKILL_USE_REFUSAL.format(name=name)


def refuse_workspace_read(rel_path: str, snapshot: list[dict] | None, enabled_of) -> str | None:
    """Sync read check. ``enabled_of(skill_id)`` is True, False, or None."""
    name = skill_directory(rel_path)
    if name is None:
        return None
    entry = snapshot_entry(snapshot, name)
    if entry is None:
        return None
    return refusal_for(name, snapshot, enabled_of(int(entry["skill_id"])))


async def arefuse_workspace_read(rel_path: str, snapshot: list[dict] | None, enabled_of) -> str | None:
    name = skill_directory(rel_path)
    if name is None:
        return None
    entry = snapshot_entry(snapshot, name)
    if entry is None:
        return None
    enabled = enabled_of(int(entry["skill_id"]))
    if hasattr(enabled, "__await__"):
        enabled = await enabled
    return refusal_for(name, snapshot, enabled)


def refuse_code(code: str, snapshot: list[dict] | None, enabled_of) -> str | None:
    """Refuse before the interpreter runs if the script touches a dead skill."""
    for name in skill_names_in_code(code):
        entry = snapshot_entry(snapshot, name)
        if entry is None:
            continue
        refusal = refusal_for(name, snapshot, enabled_of(int(entry["skill_id"])))
        if refusal:
            return refusal
    return None


async def arefuse_code(code: str, snapshot: list[dict] | None, enabled_of) -> str | None:
    for name in skill_names_in_code(code):
        entry = snapshot_entry(snapshot, name)
        if entry is None:
            continue
        enabled = enabled_of(int(entry["skill_id"]))
        if hasattr(enabled, "__await__"):
            enabled = await enabled
        refusal = refusal_for(name, snapshot, enabled)
        if refusal:
            return refusal
    return None


def load_skill_enabled_sync(skill_id: int) -> bool | None:
    """True when the row is enabled, False when disabled, None when deleted."""
    from sqlmodel import select

    from bisheng.core.context.tenant import strict_tenant_filter
    from bisheng.core.database.manager import get_sync_db_session
    from bisheng.linsight.domain.models.linsight_skill import LinsightSkill

    with strict_tenant_filter():
        with get_sync_db_session() as session:
            row = session.exec(select(LinsightSkill).where(LinsightSkill.id == skill_id)).first()
            if row is None:
                return None
            return bool(row.enabled)


async def load_skill_enabled(skill_id: int) -> bool | None:
    from bisheng.linsight.domain.models.linsight_skill import LinsightSkillDao

    row = await LinsightSkillDao.get_by_id(skill_id)
    if row is None:
        return None
    return bool(row.enabled)
