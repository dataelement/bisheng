"""Execute management user search SQL, including original contains behavior."""

from contextlib import contextmanager

import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base
from sqlmodel import Session

from bisheng.user.domain.repositories import management_search_repository as repository

Base = declarative_base()


class SearchUser(Base):
    __tablename__ = "management_search_user"
    user_id = Column(Integer, primary_key=True)
    user_name = Column(String(255))
    external_id = Column(String(255))


@pytest.fixture
def user_search(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                SearchUser(user_id=1, user_name="zeta", external_id="jia0100"),
                SearchUser(user_id=2, user_name="jia0100-name", external_id="jia0100-more"),
                SearchUser(user_id=3, user_name="literal", external_id="jia_0%"),
                SearchUser(user_id=4, user_name="contains alice", external_id=None),
                SearchUser(user_id=5, user_name="other source", external_id="jia0100"),
            ]
        )
        session.commit()

    @contextmanager
    def session_factory():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(repository, "User", SearchUser)
    monkeypatch.setattr(repository, "get_sync_db_session", session_factory)
    yield repository.ManagementSearchRepository
    engine.dispose()


def test_external_id_exact_priority_union_dedup_and_empty_page(user_search):
    rows, total = user_search.list_users(keyword="jia0100", page=1, limit=1)
    assert total == 3
    assert [row.user_id for row in rows] == [5]
    rows, total = user_search.list_users(keyword="jia0100", page=2, limit=1)
    assert [row.user_id for row in rows] == [1]
    rows, total = user_search.list_users(keyword="jia0100", page=9, limit=1)
    assert rows == []
    assert total == 3


def test_case_sensitive_id_prefix_and_literal_wildcards(user_search):
    assert user_search.list_users(keyword="0100")[1] == 1  # Name containment remains.
    assert user_search.list_users(keyword="JIA")[1] == 1  # SQLite name LIKE remains case-insensitive.
    rows, total = user_search.list_users(keyword="jia_0%")
    assert total == 1
    assert rows[0].user_id == 3


def test_original_name_contains_and_empty_allowed_scope(user_search):
    assert user_search.list_users(keyword="alice")[1] == 1
    assert user_search.list_users(user_ids=[], keyword="jia")[1] == 0
    assert user_search.list_users(user_ids=[1], keyword="jia")[1] == 1
    rows, total = user_search.list_users(keyword=" \t ")
    assert total == 5
    assert [row.user_id for row in rows] == [5, 4, 3, 2, 1]
