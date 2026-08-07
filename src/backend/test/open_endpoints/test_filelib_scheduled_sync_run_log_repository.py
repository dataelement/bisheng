from datetime import datetime, timezone

import pytest
from sqlmodel import select

from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.open_endpoints.domain.models.filelib_scheduled_sync_run_log import (
    AUTOMOTIVE_SHEET_INTRO_JOB_CODE,
    FilelibScheduledSyncRunLog,
)
from bisheng.open_endpoints.domain.repositories.implementations.filelib_scheduled_sync_run_log_repository_impl import (
    FilelibScheduledSyncRunLogRepositoryImpl,
)
from bisheng.open_endpoints.domain.repositories.interfaces.filelib_scheduled_sync_run_log_repository import (
    FilelibScheduledSyncRunLogCreate,
    FilelibScheduledSyncRunLogUpdate,
)

_NOW = datetime(2026, 7, 28, tzinfo=timezone.utc).replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _tenant():
    register_tenant_filter_events()
    set_current_tenant_id(5)
    yield
    set_current_tenant_id(None)


async def test_run_log_repository_insert_update_and_list(async_db_session):
    repo = FilelibScheduledSyncRunLogRepositoryImpl(async_db_session)
    run_id = await repo.insert(
        FilelibScheduledSyncRunLogCreate(
            tenant_id=5,
            job_code=AUTOMOTIVE_SHEET_INTRO_JOB_CODE,
            trigger_type="manual",
            status="running",
            start_time=_NOW,
            developer_token_id=10,
            file_name="汽车板介绍.pdf",
        )
    )

    await repo.update(
        run_id,
        FilelibScheduledSyncRunLogUpdate(
            status="success",
            file_id=1001,
            knowledge_id=2002,
            end_time=_NOW,
            duration_ms=1500,
        ),
    )

    rows, total = await repo.list_by_tenant(
        5,
        job_code=AUTOMOTIVE_SHEET_INTRO_JOB_CODE,
        page=1,
        limit=20,
    )
    assert total == 1
    assert len(rows) == 1
    assert rows[0].id == run_id
    assert rows[0].status == "success"
    assert rows[0].file_id == 1001
    assert rows[0].tenant_id == 5

    result = await async_db_session.exec(select(FilelibScheduledSyncRunLog))
    persisted = result.all()
    assert len(persisted) == 1
    assert persisted[0].trigger_type == "manual"


async def test_run_log_repository_lists_by_start_time_desc_with_pagination(async_db_session):
    repo = FilelibScheduledSyncRunLogRepositoryImpl(async_db_session)
    older_time = datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    newer_time = datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc).replace(tzinfo=None)

    older_id = await repo.insert(
        FilelibScheduledSyncRunLogCreate(
            tenant_id=5,
            job_code=AUTOMOTIVE_SHEET_INTRO_JOB_CODE,
            trigger_type="manual",
            status="success",
            start_time=older_time,
        )
    )
    newer_id = await repo.insert(
        FilelibScheduledSyncRunLogCreate(
            tenant_id=5,
            job_code=AUTOMOTIVE_SHEET_INTRO_JOB_CODE,
            trigger_type="scheduled",
            status="success",
            start_time=newer_time,
        )
    )

    page_one, total = await repo.list_by_tenant(
        5,
        job_code=AUTOMOTIVE_SHEET_INTRO_JOB_CODE,
        page=1,
        limit=1,
    )
    page_two, _ = await repo.list_by_tenant(
        5,
        job_code=AUTOMOTIVE_SHEET_INTRO_JOB_CODE,
        page=2,
        limit=1,
    )

    assert total == 2
    assert [row.id for row in page_one] == [newer_id]
    assert [row.id for row in page_two] == [older_id]
