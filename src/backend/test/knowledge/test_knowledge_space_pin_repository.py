from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.user_link import UserLink
from bisheng.knowledge.domain.repositories.implementations.knowledge_space_pin_repository_impl import (
    KnowledgeSpacePinRepositoryImpl,
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(UserLink.__table__.create)
    async with AsyncSession(engine, expire_on_commit=False) as db_session:
        yield db_session
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_add_and_remove_are_scoped_and_idempotent(session: AsyncSession):
    repository = KnowledgeSpacePinRepositoryImpl(session)
    session.add_all(
        [
            UserLink(user_id=1, type="other", type_detail="10"),
            UserLink(user_id=2, type="knowledge_space_pin", type_detail="10"),
        ]
    )
    await session.commit()

    assert await repository.add_pin(1, 10) is True
    assert await repository.add_pin(1, 10) is False
    assert await repository.list_for_user(1) == {10}

    assert await repository.remove_pin(1, 999) is False
    assert await repository.remove_pin(1, 10) is True
    assert await repository.list_for_user(1) == set()


@pytest.mark.asyncio
async def test_delete_by_space_id_preserves_other_types_and_spaces(session: AsyncSession):
    repository = KnowledgeSpacePinRepositoryImpl(session)
    session.add_all(
        [
            UserLink(user_id=1, type="knowledge_space_pin", type_detail="10"),
            UserLink(user_id=2, type="knowledge_space_pin", type_detail="10"),
            UserLink(user_id=1, type="knowledge_space_pin", type_detail="11"),
            UserLink(user_id=1, type="other", type_detail="10"),
        ]
    )
    await session.commit()

    assert await repository.delete_by_space_id(10) == 2
    await session.commit()
    remaining = (await session.exec(select(UserLink).order_by(UserLink.id))).all()

    assert [(item.type, item.type_detail) for item in remaining] == [
        ("knowledge_space_pin", "11"),
        ("other", "10"),
    ]


@pytest.mark.asyncio
async def test_lock_user_uses_for_update():
    session = AsyncMock()
    repository = KnowledgeSpacePinRepositoryImpl(session)

    await repository.lock_user(7)

    statement = session.exec.await_args.args[0]
    assert "FOR UPDATE" in str(statement)
