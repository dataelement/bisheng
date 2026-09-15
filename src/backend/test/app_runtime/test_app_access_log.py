"""T089a — access records: one row per *entry*, written by the entry verdict itself (AC-38).

What the record answers is "who is using this application" (PRD RT-01 / GOV-04),
so the unit is an entry, not a request: the SETNX window merges the repeats a
session produces (proxy cache misses, a refresh, the next XHR), and only an
``allow`` verdict counts — a visitor stopped by one of the fallback pages was not
using anything (F056 spec AC-24 / 决议-2).

The write is fire-and-forget (design D14-B). Every assertion about rows first
drains the pending tasks through ``flush_pending_access_records`` — the verdict
itself must never wait on Redis or the database, and the tests that prove it
(``TestFailureIsolation``) break both on purpose.

Redis is a fake with a controllable clock: the merge window is what the tests
are about, and a real Redis would make "the window expired" a 30-minute sleep.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlmodel import select

from bisheng.app_runtime.domain.constants import AppState

pytestmark = pytest.mark.usefixtures("app_db")

OBO_SECRET = "f054-obo-secret-not-the-session-one"

_ACCESS_KEY = re.compile(r"^app_access:(?P<app_id>[^:]+):(?P<user_id>\d+)$")


# ---------------------------------------------------------------------------
# fixtures (the entry-path trio mirrors test_entry_authz_service on purpose:
# this module asserts what the verdict *writes*, that one what it *answers*)
# ---------------------------------------------------------------------------


@pytest.fixture()
def runtime_enabled(monkeypatch):
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.app_runtime, "enabled", True, raising=False)
    monkeypatch.setattr(settings.app_runtime, "obo_secret", OBO_SECRET, raising=False)
    return settings


@pytest.fixture()
def visible(monkeypatch):
    from bisheng.app_runtime.domain.services import entry_authz_service

    state = {"allow": True}

    async def _check(actor, *, resource_type, resource_id, action):
        return state["allow"]

    monkeypatch.setattr(entry_authz_service, "check_business_action", _check)
    return state


@pytest.fixture()
def no_tenant_blacklist(monkeypatch):
    from bisheng.app_runtime.domain.services import entry_authz_service

    async def _disabled(tenant_id: int) -> bool:
        return False

    monkeypatch.setattr(entry_authz_service, "_tenant_disabled", _disabled)


class _FakeRedisConnection:
    """Just enough of ``redis.asyncio.Redis`` for ``SET key value NX EX``.

    ``now`` is a callable so a test can move the clock past the merge window
    instead of sleeping through it.
    """

    def __init__(self):
        self.store: dict[str, tuple[bytes, float]] = {}
        self.calls: list[dict] = []
        self.clock = {"now": 0.0}
        self.fail_with: Exception | None = None

    def advance(self, seconds: float) -> None:
        self.clock["now"] += seconds

    async def set(self, key, value, *, nx=False, ex=None, **kwargs):
        self.calls.append({"key": key, "nx": nx, "ex": ex})
        if self.fail_with is not None:
            raise self.fail_with
        now = self.clock["now"]
        current = self.store.get(key)
        if current is not None and current[1] > now:
            if nx:
                return None
        self.store[key] = (value, now + (ex or 10**9))
        return True


@pytest.fixture()
def fake_redis(monkeypatch):
    from bisheng.core.cache import redis_manager

    connection = _FakeRedisConnection()
    client = SimpleNamespace(async_connection=connection)

    async def _client():
        return client

    monkeypatch.setattr(redis_manager, "get_redis_client", _client)
    return connection


@pytest.fixture()
async def drained():
    """Await every fire-and-forget access write scheduled so far."""
    from bisheng.app_runtime.domain.services.app_access_log_service import flush_pending_access_records

    return flush_pending_access_records


def _token(user_id: int, user_name: str = "u", tenant_id: int = 1) -> str:
    from bisheng.user.domain.services.auth import AuthJwt

    return AuthJwt().create_access_token(
        {"user_id": user_id, "user_name": user_name, "tenant_id": tenant_id, "token_version": 0}
    )


async def _verdict(slug, token, request_id="req-1"):
    from bisheng.app_runtime.domain.services.entry_authz_service import authorize_entry

    return await authorize_entry(slug=slug, access_token=token, request_id=request_id)


async def _rows(app_db):
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.database.models.app_access_log import AppAccessLog

    with bypass_tenant_filter():
        async with app_db() as session:
            result = await session.exec(select(AppAccessLog).order_by(AppAccessLog.id))
            return list(result.all())


# ---------------------------------------------------------------------------
# one entry, one row
# ---------------------------------------------------------------------------


class TestOneRowPerEntry:
    async def test_one_row_per_entry_not_per_request(
        self, app_db, app_factory, app_owner, runtime_enabled, no_tenant_blacklist, visible, fake_redis, drained
    ):
        """AC-38 — the proxy re-asks on every cache miss and the browser fires a
        dozen sub-requests per page; none of that is a second *entry*."""
        _app, _ = await app_factory(slug="busy-app", state=AppState.ONLINE.value)
        token = _token(app_owner.user_id)

        for request_id in ("page", "app.js", "styles.css", "xhr-1", "xhr-2"):
            assert (await _verdict("busy-app", token, request_id=request_id))["decision"] == "allow"
        await drained()

        assert len(await _rows(app_db)) == 1

    async def test_dedup_window_setnx_merges_repeat_entries(
        self, app_db, app_factory, app_owner, runtime_enabled, no_tenant_blacklist, visible, fake_redis, drained
    ):
        """AC-38 — ``SETNX app_access:{app_id}:{user_id} EX <window>``: inside the
        window repeats merge; once it expires the next visit is a new entry."""
        from bisheng.common.services.config_service import settings

        app, _ = await app_factory(slug="window-app", state=AppState.ONLINE.value)
        token = _token(app_owner.user_id)
        window = settings.app_runtime.access_log_merge_window_seconds

        await _verdict("window-app", token)
        await _verdict("window-app", token)
        await drained()
        assert len(await _rows(app_db)) == 1

        first = fake_redis.calls[0]
        match = _ACCESS_KEY.match(first["key"])
        assert match and match["app_id"] == app.id and int(match["user_id"]) == app_owner.user_id
        assert first["nx"] is True and first["ex"] == window, "SETNX must carry the window as EX, atomically"

        fake_redis.advance(window + 1)
        await _verdict("window-app", token)
        await drained()
        assert len(await _rows(app_db)) == 2

    async def test_merge_window_default_is_1800s_per_f056_d7(self):
        """F056 design D7 / spec 决议-2 own the window: 30 minutes, not the 300 s
        the first F054 draft carried. A deployment overrides it in config.yaml."""
        from bisheng.core.config.app_runtime import AppRuntimeConf

        assert AppRuntimeConf().access_log_merge_window_seconds == 1800
        assert AppRuntimeConf(access_log_merge_window_seconds=60).access_log_merge_window_seconds == 60

    async def test_different_users_and_apps_do_not_merge(
        self,
        app_db,
        app_factory,
        app_owner,
        normal_user,
        runtime_enabled,
        no_tenant_blacklist,
        visible,
        fake_redis,
        drained,
    ):
        """The window is per ``(app, user)`` — two people opening the same app,
        or one person opening two apps, are distinct entries."""
        _one, _ = await app_factory(slug="one-app", state=AppState.ONLINE.value)
        _two, _ = await app_factory(slug="two-app", state=AppState.ONLINE.value)

        await _verdict("one-app", _token(app_owner.user_id))
        await _verdict("one-app", _token(normal_user.user_id))
        await _verdict("two-app", _token(app_owner.user_id))
        await drained()

        rows = await _rows(app_db)
        assert sorted((row.app_id, row.user_id) for row in rows) == sorted(
            [(_one.id, app_owner.user_id), (_one.id, normal_user.user_id), (_two.id, app_owner.user_id)]
        )


# ---------------------------------------------------------------------------
# what a row says, and when there is none
# ---------------------------------------------------------------------------


class TestRowContent:
    async def test_row_fields_complete(
        self, app_db, app_factory, chinese_name_user, runtime_enabled, no_tenant_blacklist, visible, fake_redis, drained
    ):
        """AC-38 — application, visitor, time and tenant, all on the row itself:
        the F056 query face filters on these without joining."""
        app, _ = await app_factory(slug="fields-app", state=AppState.ONLINE.value)
        before = datetime.now().replace(microsecond=0)

        await _verdict("fields-app", _token(chinese_name_user.user_id, chinese_name_user.user_name), request_id="rq-7")
        await drained()

        (row,) = await _rows(app_db)
        assert row.app_id == app.id
        assert row.user_id == chinese_name_user.user_id
        assert row.user_name == chinese_name_user.user_name, "the display name is stored as-is, not percent-encoded"
        assert row.tenant_id == app.tenant_id, "the app's tenant, not the token's — the row must be filterable"
        assert row.request_id == "rq-7"
        assert isinstance(row.entry_time, datetime)
        assert before <= row.entry_time <= datetime.now() + timedelta(seconds=1)

    @pytest.mark.parametrize("scenario", ("login", "forbidden", "stopped", "not_found"))
    async def test_written_only_on_allow_decision(
        self,
        scenario,
        app_db,
        app_factory,
        app_owner,
        normal_user,
        runtime_enabled,
        no_tenant_blacklist,
        visible,
        fake_redis,
        drained,
    ):
        """AC-38 / F056 AC-24 — a visitor stopped at a fallback page was not
        *using* the app. No row, and no Redis round-trip either."""
        state = AppState.STOPPED.value if scenario == "stopped" else AppState.ONLINE.value
        if scenario == "not_found":
            state = AppState.DRAFT.value
        _app, _ = await app_factory(slug=f"{scenario}-app", state=state)
        token = None if scenario == "login" else _token(normal_user.user_id)
        if scenario == "forbidden":
            visible["allow"] = False

        verdict = await _verdict(f"{scenario}-app", token)
        await drained()

        assert verdict["decision"] == scenario
        assert await _rows(app_db) == []
        assert fake_redis.calls == []


# ---------------------------------------------------------------------------
# the write never blocks the verdict
# ---------------------------------------------------------------------------


class TestFailureIsolation:
    async def test_write_failure_does_not_block_entry_when_db_is_down(
        self,
        app_db,
        app_factory,
        app_owner,
        runtime_enabled,
        no_tenant_blacklist,
        visible,
        fake_redis,
        drained,
        monkeypatch,
    ):
        """AC-38 — fire-and-forget: a broken insert is logged and swallowed; the
        visitor still gets in and the process keeps no failed task around."""
        from bisheng.app_runtime.domain.services import app_access_log_service
        from bisheng.database.models.app_access_log import AppAccessLogDao

        async def _boom(*args, **kwargs):
            raise RuntimeError("simulated database outage")

        monkeypatch.setattr(AppAccessLogDao, "ainsert", classmethod(lambda cls, *a, **kw: _boom(*a, **kw)))
        _app, _ = await app_factory(slug="db-down-app", state=AppState.ONLINE.value)

        verdict = await _verdict("db-down-app", _token(app_owner.user_id))
        assert verdict["decision"] == "allow"
        assert "headers" in verdict

        await drained()  # must not raise
        assert await _rows(app_db) == []
        assert not app_access_log_service._pending_tasks, "a failed write must not leak a task reference"

    async def test_write_failure_does_not_block_entry_when_redis_is_down(
        self, app_db, app_factory, app_owner, runtime_enabled, no_tenant_blacklist, visible, fake_redis, drained
    ):
        """Redis gone means the window cannot be checked. The row is still
        written: a duplicate inside the window is a cheaper failure than a
        silent gap in an audit asset, and the verdict is unaffected either way."""
        fake_redis.fail_with = ConnectionError("simulated redis outage")
        _app, _ = await app_factory(slug="redis-down-app", state=AppState.ONLINE.value)

        verdict = await _verdict("redis-down-app", _token(app_owner.user_id))
        assert verdict["decision"] == "allow"

        await drained()
        assert len(await _rows(app_db)) == 1

    async def test_verdict_returns_before_the_write_lands(
        self, app_db, app_factory, app_owner, runtime_enabled, no_tenant_blacklist, visible, fake_redis, drained
    ):
        """The verdict does not await the write — the task is still pending when
        ``authorize_entry`` returns, and it is the drain that lands the row."""
        from bisheng.app_runtime.domain.services import app_access_log_service

        _app, _ = await app_factory(slug="async-app", state=AppState.ONLINE.value)

        verdict = await _verdict("async-app", _token(app_owner.user_id))
        assert verdict["decision"] == "allow"
        assert app_access_log_service._pending_tasks, "the write is scheduled, not awaited, inside the verdict"

        await drained()
        assert not app_access_log_service._pending_tasks
        assert len(await _rows(app_db)) == 1


# ---------------------------------------------------------------------------
# shutdown: in-flight writes get a bounded chance to land
# ---------------------------------------------------------------------------


class TestShutdownFlush:
    async def test_flush_waits_for_a_write_that_lands_in_time(
        self, app_db, app_factory, app_owner, runtime_enabled, no_tenant_blacklist, visible, fake_redis
    ):
        """A bounded flush is what the lifespan calls: a write that finishes
        inside the budget lands, and the count of dropped records is zero."""
        from bisheng.app_runtime.domain.services.app_access_log_service import flush_pending_access_records

        _app, _ = await app_factory(slug="flush-app", state=AppState.ONLINE.value)
        await _verdict("flush-app", _token(app_owner.user_id))

        assert await flush_pending_access_records(timeout=5.0) == 0
        assert len(await _rows(app_db)) == 1

    async def test_flush_timeout_cancels_a_stuck_write_and_reports_it(self, monkeypatch):
        """A database that never answers must not hold the process open: the
        stuck task is cancelled, counted, and the task set ends up empty."""
        import asyncio

        from bisheng.app_runtime.domain.services import app_access_log_service

        stalled = asyncio.Event()

        async def _never_returns(**kwargs):
            await stalled.wait()
            return True

        monkeypatch.setattr(app_access_log_service, "record_access", _never_returns)
        task = app_access_log_service.schedule_access_record(app_id="stuck", tenant_id=1, user_id=1, user_name="u")

        dropped = await app_access_log_service.flush_pending_access_records(timeout=0.05)

        assert dropped == 1
        for _ in range(3):  # let the loop deliver the cancellation
            await asyncio.sleep(0)
        assert task.cancelled()
        assert not app_access_log_service._pending_tasks

    def test_lifespan_flushes_before_closing_the_database(self):
        """``main.lifespan`` awaits the flush on the way down, and does so
        *before* ``close_app_context`` — after it there is no session to write
        with, and the flush would only be draining failures."""
        source = (Path(__file__).resolve().parents[2] / "bisheng" / "main.py").read_text(encoding="utf-8")
        flush_at = source.find("await flush_pending_access_records(")
        close_at = source.find("await close_app_context()")
        assert flush_at != -1, "main.lifespan must flush pending access records on shutdown"
        assert close_at != -1 and flush_at < close_at, "the flush must run before the app context is closed"


# ---------------------------------------------------------------------------
# tenant isolation + query face
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    def test_module_registered_for_tenant_filtering(self):
        """Asserted first, on purpose: everything below is vacuous if the module
        is not in ``_TENANT_AWARE_MODEL_MODULES`` (design §4.3 — the fourth path)."""
        from bisheng.core.database import tenant_filter

        assert "bisheng.database.models.app_access_log" in tenant_filter._TENANT_AWARE_MODEL_MODULES
        assert "app_access_log" in tenant_filter._discover_tenant_aware_tables()

    async def test_tenant_isolation_of_access_log(self, app_db, app_factory, app_owner, sub_tenant, monkeypatch):
        """Cross-tenant reads see nothing. Wired through the module's own
        discovery + clause builder on a per-session listener, because the
        process-wide registration is deliberately kept out of this test package
        (see conftest ``_no_super_admin_probe``)."""
        from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id
        from bisheng.core.database import tenant_filter
        from bisheng.database.models.app_access_log import AppAccessLog, AppAccessLogDao

        root_app, _ = await app_factory(slug="root-app", tenant_id=1)
        sub_app, _ = await app_factory(
            slug="sub-app", tenant_id=sub_tenant.tenant_id, owner_user_id=sub_tenant.admin_user_id
        )
        with bypass_tenant_filter():
            async with app_db() as session:
                await AppAccessLogDao.ainsert(
                    session, AppAccessLog(tenant_id=1, app_id=root_app.id, user_id=app_owner.user_id, user_name="root")
                )
                await AppAccessLogDao.ainsert(
                    session,
                    AppAccessLog(
                        tenant_id=sub_tenant.tenant_id,
                        app_id=sub_app.id,
                        user_id=sub_tenant.admin_user_id,
                        user_name="sub",
                    ),
                )
                await session.commit()

        monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._discover_tenant_aware_tables())

        def _inject(state):
            if not state.is_select:
                return
            stmt = state.statement
            for table in tenant_filter._get_tenant_tables_from_statement(stmt):
                clause = tenant_filter.build_tenant_filter_clause(table.c.tenant_id)
                if clause is not None:
                    stmt = stmt.where(clause)
            state.statement = stmt

        set_current_tenant_id(sub_tenant.tenant_id)
        async with app_db() as session:
            event.listen(session.sync_session, "do_orm_execute", _inject)
            rows, total = await AppAccessLogDao.alist_page(session)
            event.remove(session.sync_session, "do_orm_execute", _inject)

        assert total == 1 and [row.app_id for row in rows] == [sub_app.id]

    async def test_query_face_filters_by_app_user_and_time_range(self, app_db, app_factory, app_owner, normal_user):
        """F056 AC-24 reads through this DAO: by application, by visitor, by time
        range, newest first with the id as the tie-breaker."""
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.database.models.app_access_log import AppAccessLog, AppAccessLogDao

        one, _ = await app_factory(slug="q-one")
        two, _ = await app_factory(slug="q-two")
        t0 = datetime(2026, 1, 1, 9, 0, 0)
        seed = [
            (one.id, app_owner.user_id, t0),
            (one.id, normal_user.user_id, t0 + timedelta(minutes=1)),
            (two.id, app_owner.user_id, t0 + timedelta(minutes=2)),
            (one.id, app_owner.user_id, t0 + timedelta(minutes=2)),  # same second as the previous one
        ]
        with bypass_tenant_filter():
            async with app_db() as session:
                for app_id, user_id, moment in seed:
                    await AppAccessLogDao.ainsert(
                        session,
                        AppAccessLog(tenant_id=1, app_id=app_id, user_id=user_id, user_name="x", entry_time=moment),
                    )
                await session.commit()

            async with app_db() as session:
                rows, total = await AppAccessLogDao.alist_page(session, app_id=one.id)
                assert total == 3 and all(row.app_id == one.id for row in rows)
                assert [row.entry_time for row in rows] == sorted((row.entry_time for row in rows), reverse=True)

                rows, total = await AppAccessLogDao.alist_page(session, user_id=normal_user.user_id)
                assert total == 1 and rows[0].user_id == normal_user.user_id

                rows, total = await AppAccessLogDao.alist_page(
                    session, start_time=t0 + timedelta(minutes=2), end_time=t0 + timedelta(minutes=3)
                )
                assert total == 2
                assert [row.id for row in rows] == sorted((row.id for row in rows), reverse=True), (
                    "ties break on id DESC"
                )

                page_one, total = await AppAccessLogDao.alist_page(session, page=1, page_size=3)
                page_two, _ = await AppAccessLogDao.alist_page(session, page=2, page_size=3)
                assert total == 4 and len(page_one) == 3 and len(page_two) == 1
                assert {row.id for row in page_one} | {row.id for row in page_two} == {1, 2, 3, 4}


# ---------------------------------------------------------------------------
# the writer is the backend, never app-proxy
# ---------------------------------------------------------------------------


class TestWriterIdentity:
    def test_app_proxy_does_not_write_directly(self):
        """AC-38 / D14-B — app-proxy holds no database: no driver dependency, no
        ORM import, no mention of the table. The record is a side effect of the
        verdict and lives where the verdict lives."""
        repo_root = Path(__file__).resolve().parents[4]
        proxy_root = repo_root / "src" / "app-proxy"
        if not proxy_root.is_dir():
            pytest.skip("src/app-proxy is not part of this checkout")

        pyproject = (proxy_root / "pyproject.toml").read_text(encoding="utf-8")
        for driver in ("sqlalchemy", "sqlmodel", "pymysql", "aiomysql", "asyncmy", "redis"):
            assert driver not in pyproject.lower(), f"app-proxy must not depend on {driver}"

        for source in (proxy_root / "app_proxy").rglob("*.py"):
            text = source.read_text(encoding="utf-8")
            for marker in ("app_access_log", "AppAccessLog", "sqlalchemy", "sqlmodel", "app_access:"):
                assert marker not in text, f"{source.relative_to(repo_root)} references {marker}"

    def test_scheduled_only_from_the_entry_verdict(self):
        """One writer: ``entry_authz_service.authorize_entry``. A second call
        site would be a second definition of what an "entry" is."""
        backend_root = Path(__file__).resolve().parents[2] / "bisheng"
        callers = sorted(
            str(path.relative_to(backend_root))
            for path in backend_root.rglob("*.py")
            if "schedule_access_record(" in path.read_text(encoding="utf-8")
            and path.name != "app_access_log_service.py"
        )
        assert callers == ["app_runtime/domain/services/entry_authz_service.py"]
