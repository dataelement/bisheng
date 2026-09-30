from datetime import datetime

from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.points.domain.models import PointSyncOutbox
from bisheng.points.domain.repositories.points_repository import PointsRepository


async def test_exhausted_legacy_rows_are_not_due():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: PointSyncOutbox.__table__.create(conn))
        async with AsyncSession(engine) as session:
            session.add_all([
                PointSyncOutbox(id=1, log_id=1, status="failed", retry_count=8),
                PointSyncOutbox(id=2, log_id=2, status="pending", retry_count=0),
            ])
            await session.commit()
            rows = await PointsRepository(session).list_due_sync_outbox(now=datetime.now())
            assert [row.id for row in rows] == [2]
    finally:
        await engine.dispose()


async def test_claim_consumes_crash_budget_and_old_owner_cannot_settle():
    from datetime import timedelta
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: PointSyncOutbox.__table__.create(conn))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(PointSyncOutbox(id=1, log_id=1, status='pending', retry_count=6))
            await session.commit()
            repo = PointsRepository(session)
            now = datetime.utcnow()
            first = await repo.claim_sync_outbox(1, 'a', now)
            assert first.retry_count == 7
            await session.commit()
            assert await repo.claim_sync_outbox(1, 'b', now) is None
            await repo.recover_sync_outbox(now + timedelta(minutes=4))
            await session.commit()
            second = await repo.claim_sync_outbox(1, 'b', now + timedelta(minutes=10))
            assert second.retry_count == 8
            await session.commit()
            assert not await repo.settle_sync_outbox(1, 'a', {'status': 'sent'})
            await repo.recover_sync_outbox(now + timedelta(minutes=14))
            await session.commit()
            assert await repo.list_due_sync_outbox(now=now + timedelta(days=1)) == []
            assert (await session.get(PointSyncOutbox, 1, populate_existing=True)).status == 'dead'
    finally:
        await engine.dispose()
