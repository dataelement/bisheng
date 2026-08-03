from __future__ import annotations

from types import SimpleNamespace

from sqlmodel import Field, SQLModel

from bisheng.user.domain.repositories.implementations import user_repository_impl
from bisheng.user.domain.repositories.implementations.user_repository_impl import (
    UserRepositoryImpl,
)


class _UserFixture(SQLModel, table=True):
    __tablename__ = "f069_user_fixture"

    user_id: int | None = Field(default=None, primary_key=True)
    source: str
    external_id: str | None = None
    delete: int = 0


class _Result:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


class _Session:
    def __init__(self, values: list[object]) -> None:
        self.values = values
        self.statements = []

    async def exec(self, statement):
        self.statements.append(statement)
        return _Result(self.values)


async def test_list_active_by_external_id_returns_all_candidates(monkeypatch) -> None:
    candidates = [
        SimpleNamespace(user_id=7, source="sso-a", external_id="EMP001", delete=0),
        SimpleNamespace(user_id=8, source="sso-b", external_id="EMP001", delete=0),
    ]
    session = _Session(candidates)
    monkeypatch.setattr(user_repository_impl, "User", _UserFixture)
    repository = UserRepositoryImpl(session)

    result = await repository.list_active_by_external_id("EMP001")

    assert result == candidates
    where_clause = str(session.statements[0].whereclause)
    assert "f069_user_fixture.external_id" in where_clause
    assert "f069_user_fixture.delete" in where_clause
    assert "f069_user_fixture.source" not in where_clause


async def test_list_active_by_external_id_preserves_empty_result(monkeypatch) -> None:
    monkeypatch.setattr(user_repository_impl, "User", _UserFixture)
    repository = UserRepositoryImpl(_Session([]))

    assert await repository.list_active_by_external_id("MISSING") == []
