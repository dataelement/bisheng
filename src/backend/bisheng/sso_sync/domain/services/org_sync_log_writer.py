"""F014 ``org_sync_log`` buffer + flush helper.

Accumulates per-call counters in memory and writes a single
:class:`OrgSyncLog` row at the end of each Gateway request. Writing a
single row per request (rather than per item) keeps the table bounded to
"one row per Gateway roundtrip" which matches how the existing F009
management UI renders history.

``config_id`` resolves from :attr:`SSOSyncConf.orphan_config_id` (default
9999) — the migration seeds that row as a disabled synthetic config so
the UI join works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from loguru import logger

from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.org_sync.domain.models.org_sync import (
    OrgSyncLog,
    OrgSyncLogDao,
)


@dataclass
class OrgSyncLogBuffer:
    """Per-request counter accumulator. Populated by the service flow,
    flushed once via :func:`flush_log` right before the API response."""

    dept_created: int = 0
    dept_updated: int = 0
    dept_archived: int = 0
    member_created: int = 0
    member_updated: int = 0
    member_disabled: int = 0
    member_reactivated: int = 0
    errors: List[dict] = field(default_factory=list)
    warnings: List[dict] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.utcnow)

    def warn(self, event_type: str, external_id: str, **kwargs) -> None:
        self.warnings.append({
            'event_type': event_type,
            'external_id': external_id,
            **kwargs,
        })

    def error(self, event_type: str, external_id: str, err: str) -> None:
        self.errors.append({
            'entity_type': event_type,
            'external_id': external_id,
            'error_msg': err,
        })


async def flush_log(
    buffer: OrgSyncLogBuffer,
    *,
    trigger_type: str,
    status: Optional[str] = None,
    config_id: Optional[int] = None,
    trigger_user: Optional[int] = None,
) -> Optional[OrgSyncLog]:
    """Persist the buffer as a single :class:`OrgSyncLog` row.

    Best-effort: a logging failure must never break an otherwise-successful
    sync response. Returns the created row, or None when the write failed.
    """
    try:
        resolved_config_id = (
            config_id
            if config_id is not None
            else int(settings.sso_sync.orphan_config_id or 9999)
        )
    except Exception:  # pragma: no cover — MagicMock-ish settings in tests
        resolved_config_id = 9999

    resolved_status = status or (
        'partial' if buffer.errors else 'success'
    )

    log = OrgSyncLog(
        tenant_id=ROOT_TENANT_ID,
        config_id=resolved_config_id,
        trigger_type=trigger_type,
        trigger_user=trigger_user,
        status=resolved_status,
        dept_created=buffer.dept_created,
        dept_updated=buffer.dept_updated,
        dept_archived=buffer.dept_archived,
        member_created=buffer.member_created,
        member_updated=buffer.member_updated,
        member_disabled=buffer.member_disabled,
        member_reactivated=buffer.member_reactivated,
        error_details=(buffer.errors + buffer.warnings) or None,
        start_time=buffer.start_time,
        end_time=datetime.utcnow(),
    )
    # The endpoint calls flush_log *after* the service returns, by which
    # point the bypass_tenant_filter + current_tenant_id context set up
    # inside the service has already been torn down. Re-enter it here so
    # the write bypasses the F001 tenant-scoping event hooks (the log row
    # is tenant_id=1 by design, not the caller's JWT leaf).
    try:
        with bypass_tenant_filter():
            token = set_current_tenant_id(ROOT_TENANT_ID)
            try:
                return await OrgSyncLogDao.acreate(log)
            finally:
                current_tenant_id.reset(token)
    except Exception as e:  # pragma: no cover
        logger.warning('F014 org_sync_log flush failed: %s', e)
        return None
