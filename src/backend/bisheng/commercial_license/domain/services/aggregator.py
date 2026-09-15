from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from loguru import logger

from bisheng.commercial_license.domain.mappers import (
    LICENSE_CODES,
    compute_days_remaining,
    compute_display_state,
)
from bisheng.commercial_license.domain.repositories.license_info_repository import LicenseInfoRepository

EtlSync = Callable[[], Awaitable[None]]
DashboardHttp = Callable[[], Awaitable[None]]

ETL_STALE_AFTER = timedelta(hours=1)


def _is_stale(checked_at: datetime | None, now: datetime) -> bool:
    if checked_at is None:
        return True
    checked = checked_at.replace(tzinfo=None) if checked_at.tzinfo else checked_at
    current = now.replace(tzinfo=None) if now.tzinfo else now
    return current - checked > ETL_STALE_AFTER


async def list_license_status(
    now: datetime,
    *,
    repo: LicenseInfoRepository,
    etl_sync: EtlSync | None = None,
    dashboard_http: DashboardHttp | None = None,
) -> dict:
    del dashboard_http  # BISHENG never pulls dashboard license over HTTP.
    etl_row = await repo.get_by_code("etl")
    if etl_sync is not None and (etl_row is None or _is_stale(etl_row.checked_at, now)):
        try:
            await etl_sync()
        except Exception:
            logger.warning("etl license refresh failed during aggregate license_code={}", "etl")
    rows = await repo.get_all()
    today = now.date()
    licenses = []
    for row in rows:
        if row.license_code not in LICENSE_CODES:
            continue
        days = compute_days_remaining(row.expire_date, row.days_remaining, today)
        licenses.append(
            {
                "license_code": row.license_code,
                "license_name": row.license_code,
                "display_state": compute_display_state(row.expire_date, row.days_remaining, today),
                "expire_date": row.expire_date.isoformat() if row.expire_date else None,
                "days_remaining": days,
                "checked_at": row.checked_at.isoformat() if row.checked_at else None,
            }
        )
    return {
        "licenses": licenses,
        "checked_at": now.isoformat(),
    }
