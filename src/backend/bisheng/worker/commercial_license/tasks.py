"""Celery task — hourly ETL license refresh (F070).

Deployment-level: do not pass tenant_id, do not iterate tenants, do not
restore a tenant ContextVar. Authorization is not tenant-scoped (INV-35).
"""

from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(
    acks_late=True,
    time_limit=120,
    soft_time_limit=90,
    name="bisheng.worker.commercial_license.tasks.refresh_etl_license",
)
def refresh_etl_license():
    run_async_task(_refresh_etl_license)


async def _refresh_etl_license() -> None:
    from bisheng.commercial_license.domain.repositories.license_info_repository import LicenseInfoRepository
    from bisheng.commercial_license.domain.services.etl_sync import sync_etl_license
    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        await sync_etl_license(LicenseInfoRepository(session))
