"""F003 T009: organisation dimension of runtime records (design decision 10). 覆盖 AC: AC-20, AC-42."""

import csv
import io
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.datastructures import QueryParams

from bisheng.app_governance.api.router import filters as router_filters
from bisheng.app_governance.domain.repositories.runtime_audit_repository import RuntimeAuditRepository
from bisheng.app_governance.domain.schemas.runtime_audit import AuthorizedRuntimeAuditScope, normalize
from bisheng.app_governance.domain.services.runtime_audit_export_service import csv_bytes
from bisheng.common.errcode.app_governance import RuntimeAuditFilterInvalidError
from bisheng.common.services.config_service import settings
from bisheng.database.models.app_access_log import AppAccessLog
from bisheng.database.models.org_snapshot import AuditDeptScope
from test.fixtures.table_definitions import TABLE_DEFINITIONS

_DEPTS = [(1, "/1/"), (2, "/1/2/"), (3, "/1/2/3/"), (20, "/1/20/")]
# access row id -> operator_dept_id
_ROWS = {1: 2, 2: 3, 3: 20, 4: 0, 5: None, 6: -1}


@pytest.fixture(autouse=True)
def utc_source(monkeypatch):
    monkeypatch.setattr(settings.app_runtime, "runtime_audit_source_timezone", "UTC")


class TestFilterParsing:
    def test_dept_ids_comma_string_dedup_sorted(self):
        requested, frozen = normalize("access", {"dept_ids": "3, 1,3", "include_descendants": "false"})
        assert requested["dept_ids"] == [1, 3]
        assert requested["include_descendants"] is False
        assert frozen["dept_ids"] == [1, 3]

    @pytest.mark.parametrize(
        "bad",
        [
            {"dept_ids": "0"},
            {"dept_ids": "-1,2"},
            {"dept_ids": "a"},
            {"dept_ids": ","},
            {"include_none": "yes"},
            {"include_unrecorded": "1"},
        ],
    )
    def test_invalid_values_rejected(self, bad):
        with pytest.raises(RuntimeAuditFilterInvalidError):
            normalize("access", bad)

    def test_router_copies_dept_keys(self):
        request = SimpleNamespace(query_params=QueryParams("dept_ids=2,3&include_none=true&kind=access"))
        assert router_filters(request, candidate=True) == {"dept_ids": "2,3", "include_none": "true"}

    def test_router_still_rejects_repeated_keys(self):
        request = SimpleNamespace(query_params=QueryParams("dept_ids=2&dept_ids=3"))
        with pytest.raises(RuntimeAuditFilterInvalidError):
            router_filters(request)


@pytest.fixture()
async def repo():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.execute(text(TABLE_DEFINITIONS["department"]))
        await conn.run_sync(lambda sync: AppAccessLog.__table__.create(sync))
        for dept_id, path in _DEPTS:
            await conn.execute(
                text(
                    "INSERT INTO department (id, dept_id, name, path, status, tenant_id) "
                    "VALUES (:i, :c, :n, :p, 'active', 1)"
                ),
                {"i": dept_id, "c": f"BS@{dept_id}", "n": f"d{dept_id}", "p": path},
            )
        for row_id, dept_id in _ROWS.items():
            await conn.execute(
                insert(AppAccessLog.__table__).values(
                    id=row_id,
                    tenant_id=1,
                    app_id="app-a",
                    user_id=100 + row_id,
                    entry_time=datetime(2026, 11, 1),
                    operator_dept_id=dept_id,
                )
            )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine) as one:
            yield one

    yield RuntimeAuditRepository(sessions)
    await engine.dispose()


def _scope(dept_scope=None):
    return AuthorizedRuntimeAuditScope(7, 1, 1, ("app-a",), dept_scope)


async def _ids(repo, scope, **selection):
    _, frozen = normalize("access", {"time_range": "all", **selection})
    rows = await repo.page(scope, "access", frozen, 10**6, limit=50)
    return sorted(row["id"] for row in rows)


class TestRepositoryScope:
    async def test_admin_without_selection_sees_everything(self, repo):
        assert await _ids(repo, _scope()) == [1, 2, 3, 4, 5, 6]

    async def test_admin_selection_with_fixed_options(self, repo):
        ids = await _ids(repo, _scope(), dept_ids="2", include_none="true", include_unrecorded="true")
        assert ids == [1, 2, 4, 5]

    async def test_dept_admin_limited_to_closure(self, repo):
        scope = _scope(AuditDeptScope.restricted(admin_paths=["/1/2/"]))
        assert await _ids(repo, scope) == [1, 2]

    async def test_dept_admin_cannot_widen_by_parameters(self, repo):
        scope = _scope(AuditDeptScope.restricted(admin_paths=["/1/2/"]))
        ids = await _ids(repo, scope, dept_ids="20", include_none="true", include_unrecorded="true")
        assert ids == []

    async def test_menu_role_primary_only(self, repo):
        scope = _scope(AuditDeptScope.restricted(exact_ids=[3]))
        assert await _ids(repo, scope) == [2]

    async def test_without_descendants(self, repo):
        assert await _ids(repo, _scope(), dept_ids="2", include_descendants="false") == [1]

    async def test_candidates_follow_scope(self, repo):
        scope = _scope(AuditDeptScope.restricted(admin_paths=["/1/2/"]))
        _, frozen = normalize("access", {"time_range": "all"})
        result = await repo.candidates(scope, "access", "visitor", frozen)
        assert sorted(item["id"] for item in result["items"]) == ["101", "102"]

    def test_digest_tracks_dept_scope(self):
        assert _scope().digest != _scope(AuditDeptScope.restricted(exact_ids=[3])).digest
        assert (
            _scope(AuditDeptScope.restricted(exact_ids=[3])).digest
            != _scope(AuditDeptScope.restricted(exact_ids=[4])).digest
        )


class TestResolveScope:
    @pytest.fixture()
    def env(self, monkeypatch):
        from bisheng.app_governance.domain.services import runtime_audit_scope as module
        from bisheng.common.dependencies.user_deps import UserPayload

        state = SimpleNamespace(tenant_admin=False, global_super=False, resolved=[])

        async def account(*args):
            return SimpleNamespace(token_version=0)

        async def fresh(**kwargs):
            return SimpleNamespace(is_global_super=state.global_super, user_id=7, tenant_id=1)

        async def own(*args, **kwargs):
            return SimpleNamespace(tenant_id=1)

        async def editable(*args):
            return ("app-a",)

        async def menu_ok(*args):
            return None

        async def tenant_admin(*args):
            return state.tenant_admin

        async def resolve(user, tenant):
            state.resolved.append(tenant)
            return AuditDeptScope.restricted(exact_ids=[3])

        async def authorize(*args):
            return None

        monkeypatch.setattr(RuntimeAuditRepository, "current_user", account)
        monkeypatch.setattr(UserPayload, "init_login_user", fresh)
        monkeypatch.setattr(UserPayload, "assert_effective_web_menu_contains", menu_ok)
        monkeypatch.setattr(module, "resolve_management_scope", own)
        monkeypatch.setattr(module, "editable_app_ids", editable)
        monkeypatch.setattr(module, "is_tenant_admin", tenant_admin)
        monkeypatch.setattr(module, "authorize_app", authorize)
        monkeypatch.setattr(module.AuditDeptScopeService, "resolve", resolve)
        return module, state, UserPayload(user_id=7, user_name="u", tenant_id=1, user_role=[])

    async def test_menu_entry_gets_dept_scope(self, env):
        from bisheng.core.context.tenant import tenant_execution_scope

        module, state, user = env
        with tenant_execution_scope(1):
            scope = await module.resolve_scope(user)
        assert scope.dept_scope == AuditDeptScope.restricted(exact_ids=[3])
        assert state.resolved == [1]

    async def test_tenant_admin_gets_dept_scope(self, env):
        from bisheng.core.context.tenant import tenant_execution_scope

        module, state, user = env
        state.tenant_admin = True
        with tenant_execution_scope(1):
            scope = await module.resolve_scope(user)
        assert scope.dept_scope == AuditDeptScope.restricted(exact_ids=[3])
        assert state.resolved == [1]

    async def test_rbac_super_tenant_admin_still_gets_dept_scope(self, env):
        from bisheng.core.context.tenant import tenant_execution_scope

        module, state, user = env
        state.tenant_admin = True
        state.global_super = True
        with tenant_execution_scope(1):
            scope = await module.resolve_scope(user)
        assert scope.dept_scope == AuditDeptScope.restricted(exact_ids=[3])
        assert state.resolved == [1]

    async def test_per_app_grant_unlimited(self, env):
        from bisheng.core.context.tenant import tenant_execution_scope

        module, state, user = env
        with tenant_execution_scope(1):
            scope = await module.resolve_scope(user, app_id="app-a")
        assert scope.dept_scope is None and state.resolved == []


def test_csv_writes_sentinel_text():
    rows = [
        {"id": 1, "operator_dept_id": None, "operator_dept_path": None},
        {"id": 2, "operator_dept_id": 0, "operator_dept_path": None},
        {"id": 3, "operator_dept_id": -1, "operator_dept_path": None},
        {"id": 4, "operator_dept_id": 3, "operator_dept_path": "总公司/研发部"},
    ]
    raw = csv_bytes(("id", "operator_dept_path"), rows, header=True).decode("utf-8-sig")
    parsed = list(csv.reader(io.StringIO(raw)))
    assert [line[1] for line in parsed[1:]] == ["未记录", "无所属部门", "不适用", "总公司/研发部"]
