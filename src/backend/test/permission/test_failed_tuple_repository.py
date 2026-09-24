from datetime import datetime, timedelta

from sqlalchemy import create_engine, text
from sqlmodel import Session

from bisheng.database.models.failed_tuple import FailedTuple
from bisheng.permission.domain.repositories.implementations.failed_tuple_repository_impl import FailedTupleRepositoryImpl


def test_ordering_budget_and_late_settlement():
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('''CREATE TABLE failed_tuple (
            id INTEGER PRIMARY KEY, action VARCHAR(8), fga_user VARCHAR(256), relation VARCHAR(64),
            object VARCHAR(256), retry_count INTEGER, max_retries INTEGER, status VARCHAR(16),
            error_message TEXT, tenant_id INTEGER, create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            update_time DATETIME DEFAULT CURRENT_TIMESTAMP, lease_owner VARCHAR(64), lease_until DATETIME,
            next_retry_at DATETIME)'''))
    now = datetime.utcnow()
    with Session(engine) as session:
        for row_id, action, user in [(1, 'write', 'user:1'), (2, 'delete', 'user:1'), (3, 'write', 'user:2')]:
            session.add(FailedTuple(id=row_id, action=action, fga_user=user, relation='viewer', object='knowledge:1', tenant_id=1))
        session.commit()
        repo = FailedTupleRepositoryImpl(session)
        rows = repo.claim('a', now)
        assert [row.id for row in rows] == [1, 3]
        assert [row.retry_count for row in rows] == [1, 1]
        session.commit()
        assert repo.settle('wrong', {1: None}, now) == 0
        assert repo.settle('a', {1: None, 3: 'timeout'}, now) == 2
        session.commit()
        assert [row.id for row in repo.claim('b', now)] == [2]
        repo.settle('b', {2: None}, now)
        session.commit()
        for number in range(2, 4):
            now += timedelta(minutes=6)
            rows = repo.claim(str(number), now)
            assert [row.id for row in rows] == [3]
            assert rows[0].retry_count == number
            if number == 2:
                repo.settle(str(number), {3: "timeout"}, now)
            session.commit()
        now += timedelta(minutes=6)
        assert repo.claim('last', now) == []
        session.commit()
        assert repo.settle('3', {3: None}, now) == 0
        assert session.get(FailedTuple, 3, populate_existing=True).status == 'dead'
    engine.dispose()
