"""Business-owned identity facts for F048 failed-tuple reconciliation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from bisheng.tenant.domain.services import permission_migration_source
from bisheng.tenant.domain.services.permission_migration_source import (
    LegacyIdentityPermissionMigrationSource,
)


class _Result:
    def __init__(self, rows: list[tuple[int, int]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[int, int]]:
        return self._rows


class _Session:
    async def execute(self, statement) -> _Result:
        table_names = {table.name for table in statement.get_final_froms()}
        if "user_tenant" in table_names:
            return _Result([(1, 2)])
        if "user_department" in table_names:
            return _Result([(3, 4)])
        raise AssertionError(f"unexpected identity query: {table_names}")


async def test_identity_source_returns_supported_canonical_memberships(
    monkeypatch,
) -> None:
    @asynccontextmanager
    async def get_async_db_session() -> AsyncIterator[_Session]:
        yield _Session()

    monkeypatch.setattr(
        permission_migration_source,
        "get_async_db_session",
        get_async_db_session,
    )
    identities = (
        ("user:1", "member", "tenant:2"),
        ("user:1", "member", "tenant:9"),
        ("user:3", "member", "department:4"),
        ("user:3", "member", "department:8"),
        ("user:3", "owner", "workflow:wf-1"),
    )

    states = await LegacyIdentityPermissionMigrationSource().aresolve_expected_states(identities)

    assert states == {
        identities[0]: True,
        identities[1]: False,
        identities[2]: True,
        identities[3]: False,
    }
