"""Ownership for workflow report templates (issue #2190).

A report template is one object in storage named after its ``version_key``
(``workflow/report/<version_key>.docx``). Nothing tied that name to a workflow,
so any logged-in user could read, copy or overwrite another workflow's template
just by naming its key -- and the key is plainly visible to anyone who can open
the workflow.

Ownership is carried **by the key itself**: a template minted for a workflow is
named ``<workflow_id>-<random>``. Forging the owner means renaming the file,
which points at a different object, so the check cannot be defeated by editing
workflow data (which the caller controls). Keys from before this change carry no
owner; they keep the old behaviour and are adopted into a workflow the first
time somebody with edit rights opens them.

The save callback carries no user identity -- the document server posts it, not
the browser -- so "may this person save?" is decided when the editor URL is
handed out (which is authenticated) and remembered for the callback to read.
"""

import hashlib
import json
import re

from loguru import logger

from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.utils import generate_uuid

# A template that is open in an editor. The document server posts its save
# callback shortly after the editor closes, so a day covers any real session
# while keeping a stolen key from staying usable indefinitely.
EDIT_SESSION_TTL_SECONDS = 24 * 3600

_UUID_HEX = re.compile(r"^[0-9a-f]{32}$")


def storage_key(version_key: str) -> str:
    """Strip the ``_<timestamp>`` suffix the editor appends to a key."""
    return str(version_key or "").split("_", 1)[0]


def mint_version_key(workflow_id: str) -> str:
    """Name a new template after the workflow that owns it."""
    return f"{workflow_id}-{generate_uuid()}"


def adopted_version_key(workflow_id: str, legacy_key: str) -> str:
    """Name an adopted pre-ownership template, deterministically.

    Derived from the pair rather than random so that adopting the same template
    twice lands on the same object: until the workflow is saved its node still
    points at the legacy key, and every open adopts again. A fresh random name
    each time would leave each round of edits under a key nothing references.
    """
    digest = hashlib.sha256(f"{workflow_id}:{storage_key(legacy_key)}".encode()).hexdigest()
    return f"{workflow_id}-{digest[:32]}"


def owner_workflow_id(version_key: str) -> str | None:
    """Return the owning workflow id, or None for a key minted before this change."""
    key = storage_key(version_key)
    owner, _, random_part = key.partition("-")
    if not random_part or not _UUID_HEX.match(owner) or not _UUID_HEX.match(random_part):
        return None
    return owner


def _session_cache_key(version_key: str) -> str:
    return f"workflow:report:edit_session:{storage_key(version_key)}"


async def aremember_edit_session(*, version_key: str, workflow_id: str, can_edit: bool) -> None:
    """Record who the editor was opened for, for the save callback to consult."""
    redis = await get_redis_client()
    await redis.aset(
        _session_cache_key(version_key),
        json.dumps({"workflow_id": workflow_id, "can_edit": bool(can_edit)}),
        EDIT_SESSION_TTL_SECONDS,
    )


async def aget_edit_session(version_key: str) -> dict | None:
    """Return the recorded editor session for a key, or None when there is none."""
    redis = await get_redis_client()
    raw = await redis.aget(_session_cache_key(version_key))
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        session = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("report template: unreadable edit session for key={!r}", storage_key(version_key))
        return None
    return session if isinstance(session, dict) else None


def iter_report_keys(flow_data: object):
    """Yield the storage keys of every report node in a flow/template payload."""
    if not isinstance(flow_data, dict):
        return
    for node in flow_data.get("nodes") or []:
        data = node.get("data") if isinstance(node, dict) else None
        if not isinstance(data, dict) or data.get("type") != "report":
            continue
        for group in data.get("group_params") or []:
            for param in (group or {}).get("params") or []:
                if param.get("key") != "report_info":
                    continue
                value = param.get("value") or {}
                key = storage_key(value.get("version_key") or "")
                if key:
                    yield key


async def ais_app_template_asset(version_key: str) -> bool:
    """True when the key belongs to a published app template.

    "Create app from template" copies the template's report node, and the
    template was authored inside a workflow the copying user cannot access --
    so checking the owning workflow alone would refuse a legitimate copy. The
    template table is a small curated list, so scanning it in Python keeps the
    query portable across both supported databases.
    """
    from sqlmodel import select

    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.template import Template

    key = storage_key(version_key)
    if not key:
        return False
    async with get_async_db_session() as session:
        rows = (await session.execute(select(Template.data))).scalars().all()
    return any(key in iter_report_keys(row) for row in rows)
