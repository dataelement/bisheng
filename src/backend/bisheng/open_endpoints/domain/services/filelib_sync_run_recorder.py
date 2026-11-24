"""Best-effort writer for developer-token sync records (shared run log table)."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from loguru import logger

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.database import get_async_db_session
from bisheng.open_endpoints.domain.models.filelib_scheduled_sync_run_log import (
    AUTOMOTIVE_SHEET_INTRO_JOB_CODE,
)
from bisheng.open_endpoints.domain.repositories.implementations.filelib_scheduled_sync_run_log_repository_impl import (
    FilelibScheduledSyncRunLogRepositoryImpl,
)
from bisheng.open_endpoints.domain.repositories.interfaces.filelib_scheduled_sync_run_log_repository import (
    FilelibScheduledSyncRunLogCreate,
)

FILELIB_FILE_SYNC_JOB_CODE = "filelib_file_sync"
FILELIB_INSPECTION_STANDARD_SYNC_JOB_CODE = "filelib_inspection_standard_sync"

SYNC_RECORD_ERROR_LIMIT_BYTES = 16384
_TRUNCATION_MARKER = "\n[truncated]"
_TOKEN_HEADER_RE = re.compile(
    r"(?i)(x-developer-token\s*[:=]\s*)([^\s,;]+)",
)


def job_code_to_interface_label(job_code: str) -> str:
    mapping = {
        AUTOMOTIVE_SHEET_INTRO_JOB_CODE: "汽车板介绍同步",
        FILELIB_FILE_SYNC_JOB_CODE: "POST /api/v2/filelib/file/sync",
        FILELIB_INSPECTION_STANDARD_SYNC_JOB_CODE: "POST /api/v2/filelib/inspection-standard/sync",
    }
    return mapping.get(str(job_code or ""), str(job_code or "-"))


def is_error_message_truncated(message: str | None) -> bool:
    return bool(message) and str(message).endswith(_TRUNCATION_MARKER)


def format_sync_exception_message(exc: BaseException) -> str:
    if isinstance(exc, BaseErrorCode):
        return str(exc.message)
    return str(exc)


def prepare_sync_error_message(
    raw: str | None, *, limit: int = SYNC_RECORD_ERROR_LIMIT_BYTES
) -> tuple[str | None, bool]:
    """Return (stored_message, truncated). Applies redact then UTF-8 byte truncate."""
    if raw is None:
        return None, False
    text = _redact_developer_token_secrets(str(raw))
    if not text:
        return None, False
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    marker = _TRUNCATION_MARKER.encode("utf-8")
    keep = max(0, limit - len(marker))
    clipped = encoded[:keep].decode("utf-8", errors="ignore")
    return f"{clipped}{_TRUNCATION_MARKER}", True


def _redact_developer_token_secrets(text: str) -> str:
    return _TOKEN_HEADER_RE.sub(r"\1[REDACTED]", text)


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def record_sync_run_finished(
    *,
    tenant_id: int,
    developer_token_id: int,
    job_code: str,
    trigger_type: str,
    status: str,
    start_time: datetime,
    end_time: datetime | None = None,
    duration_ms: int | None = None,
    file_name: str | None = None,
    file_id: int | None = None,
    knowledge_id: int | None = None,
    error_message: str | None = None,
) -> None:
    """Insert one finished (or terminal) sync run; never raise to callers."""
    try:
        stored_error, _truncated = prepare_sync_error_message(error_message)
        finished_at = end_time or utc_now_naive()
        payload = FilelibScheduledSyncRunLogCreate(
            tenant_id=int(tenant_id),
            job_code=str(job_code),
            trigger_type=str(trigger_type),
            status=str(status),
            start_time=start_time,
            developer_token_id=int(developer_token_id),
            file_id=file_id,
            knowledge_id=knowledge_id,
            file_name=file_name,
            error_message=stored_error,
            end_time=finished_at,
            duration_ms=duration_ms,
        )
        async with get_async_db_session() as session:
            await FilelibScheduledSyncRunLogRepositoryImpl(session).insert(payload)
            await session.commit()
    except Exception:
        logger.exception(
            "filelib sync run record failed token_id={} job_code={} status={}",
            developer_token_id,
            job_code,
            status,
        )
