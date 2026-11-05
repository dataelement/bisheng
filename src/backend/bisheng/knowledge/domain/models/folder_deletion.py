"""State stored only on knowledge-space directory rows."""

from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from bisheng.common.errcode.knowledge_space import SpaceFileChangeConflictError

RESERVED_KEY = "_folder_delete"
STALE_AFTER = timedelta(seconds=60)


class FolderStatus(IntEnum):
    NORMAL = 2
    DELETING = 8


class DeletionStatus(BaseModel):
    folder_id: int
    operation_id: str | None = None
    state: Literal["idle", "running", "unknown", "succeeded", "failed", "approval_pending", "untracked", "unavailable"]
    retry_after_ms: int | None = None
    failure_reason: str | None = None
    can_reconcile: bool = False


def public_metadata(metadata: dict | None) -> dict:
    return {key: value for key, value in (metadata or {}).items() if key != RESERVED_KEY}


def as_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def make_marker(token: str, user_id: int, now: datetime) -> dict:
    return {
        "version": 1,
        "operation_id": token,
        "initiator_user_id": user_id,
        "phase": "running",
        "started_at": now.isoformat(),
        "heartbeat_at": now.isoformat(),
        "failure_reason": None,
        "approval_request_id": None,
    }


def diagnostic_token(folder) -> str | None:
    marker = (folder.user_metadata or {}).get(RESERVED_KEY)
    token = marker.get("operation_id") if isinstance(marker, dict) else None
    try:
        return token if isinstance(token, str) and str(UUID(token)) == token else None
    except ValueError:
        return None


def marker_for(folder):
    data = (folder.user_metadata or {}).get(RESERVED_KEY)
    if not diagnostic_token(folder) or data.get("version") != 1:
        return None
    try:
        if type(data["initiator_user_id"]) is not int or data["initiator_user_id"] <= 0:
            return None
        if data.get("phase") not in {"running", "failed", "approval_pending"}:
            return None
        if data.get("phase") == "approval_pending" and type(data.get("approval_request_id")) is not int:
            return None
        as_utc(data["heartbeat_at"])
        as_utc(data["started_at"])
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
    return data


def ensure_source_unchanged(folder, snapshot):
    """A stable folder id must not carry an old deletion across a move or rename."""
    if "old_name" in snapshot and snapshot["old_name"] != folder.file_name:
        raise SpaceFileChangeConflictError()
    if "source_level" in snapshot and snapshot["source_level"] != int(folder.level or 0):
        raise SpaceFileChangeConflictError()
    if "source_path" in snapshot and (snapshot["source_path"] or "") != (folder.file_level_path or ""):
        raise SpaceFileChangeConflictError()


def ensure_owner(folder, token):
    marker = marker_for(folder) if folder else None
    if not (
        folder
        and folder.file_type == 0
        and folder.status == FolderStatus.DELETING
        and marker
        and marker["operation_id"] == token
        and marker.get("phase") == "running"
    ):
        raise SpaceFileChangeConflictError()


def project_folder(folder, now: datetime) -> DeletionStatus:
    marker = marker_for(folder)
    item = DeletionStatus(folder_id=folder.id, state="idle", operation_id=diagnostic_token(folder))
    if folder.status == FolderStatus.DELETING:
        fresh = (
            marker and marker.get("phase") == "running" and as_utc(now) - as_utc(marker["heartbeat_at"]) < STALE_AFTER
        )
        item.state = "running" if fresh else "unknown"
        item.retry_after_ms = 3000
    elif marker:
        if marker.get("phase") == "failed":
            item.state = "failed"
            reason = marker.get("failure_reason")
            item.failure_reason = reason if reason in {"interrupted", "delete_failed"} else "delete_failed"
        elif marker.get("phase") == "approval_pending":
            item.state = "approval_pending"
        else:
            item.state = "unknown"
    return item
