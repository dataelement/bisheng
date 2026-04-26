"""Tenant-scope visibility tests for the audit page (v2.5.0 fix).

Covers:
  - ``AuditLogDao.get_audit_logs(tenant_scope=...)``           (system-ops tab)
  - ``AuditLogDao.get_all_operators(tenant_scope=...)``        (operator dropdown)
  - ``AuditLogService._get_audit_tenant_scope`` role matrix    (helper)
  - ``MessageSession.tenant_id`` predicate semantics           (app-usage tab)
  - Service-layer end-to-end for all three audit endpoints      (real bug repro)

Background: a Child Tenant Admin opened ``/审计`` and could still see Root
tenant data because ``LoginUser.is_admin()`` is role-based (true for
non-super tenant admins too) and the F012 ``visible_tenant_ids`` IN-list
defaults to ``{leaf, 1}`` for shared-resource visibility — both effects
combined leak Root audit rows into Child Admin views. The fix scopes audit
reads via ``user.is_global_super`` + ``get_current_tenant_id()``.

Test strategy mirrors ``test_audit_log_v2.py``: a self-contained SQLite
engine + Session, monkeypatching the DAO's ``get_sync_db_session`` /
``bypass_tenant_filter`` so we exercise the real DAO body against the
predicate without spinning up the full service stack.
"""

# Pre-mock the modules audit_log eagerly imports that aren't available in the
# unit-test environment (a stale ``telemetry_search`` .pyc with bad magic
# number; the v1 router chain that drags in heavy ML deps). Conftest's own
# pre-mocks for ``bisheng.common.services`` etc. remain untouched and let
# the auth → user_deps chain resolve via MagicMock.
import sys as _sys  # noqa: E402
from unittest.mock import MagicMock as _MagicMock  # noqa: E402

_router_stub = _MagicMock()
_router_stub.router = _MagicMock()
_router_stub.router_rpc = _MagicMock()
for _m in (
    'bisheng.api.router',
    'bisheng.api.v1',
    'bisheng.api.v1.assistant',
    'bisheng.api.v1.schema',
    'bisheng.api.v1.schema.chat_schema',
    'bisheng.api.v1.schema.workflow',
    'bisheng.api.v1.schemas',
    'bisheng.telemetry_search',
    'bisheng.telemetry_search.api',
    'bisheng.telemetry_search.api.router',
):
    _sys.modules.setdefault(_m, _router_stub)

from contextlib import contextmanager, nullcontext  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, and_, func, select  # noqa: E402

from bisheng.api.services.audit_log import AuditLogService  # noqa: E402
from bisheng.database.models.audit_log import AuditLog, AuditLogDao  # noqa: E402
from bisheng.database.models.session import MessageSession  # noqa: E402


# ---------------------------------------------------------------------------
# SQLite test engine + session
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def dao_engine():
    """SQLite engine with v2.5.1 ``auditlog`` + ``message_session`` schemas."""
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS auditlog (
                id VARCHAR(255) PRIMARY KEY,
                operator_id INTEGER NOT NULL,
                operator_name VARCHAR(255),
                group_ids JSON,
                system_id VARCHAR(64),
                event_type VARCHAR(64),
                object_type VARCHAR(64),
                object_id VARCHAR(64),
                object_name TEXT,
                note TEXT,
                ip_address VARCHAR(64),
                tenant_id INTEGER,
                operator_tenant_id INTEGER,
                action VARCHAR(64),
                target_type VARCHAR(32),
                target_id VARCHAR(64),
                reason TEXT,
                metadata JSON,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS message_session (
                chat_id VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255),
                flow_id VARCHAR(255),
                flow_type INTEGER NOT NULL,
                flow_name VARCHAR(255),
                flow_description TEXT,
                flow_logo TEXT,
                user_id INTEGER NOT NULL,
                tenant_id INTEGER NOT NULL DEFAULT 1,
                group_ids JSON,
                is_delete BOOLEAN DEFAULT 0,
                "like" INTEGER DEFAULT 0,
                dislike INTEGER DEFAULT 0,
                copied INTEGER DEFAULT 0,
                sensitive_status INTEGER DEFAULT 1,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        """))
    yield engine
    engine.dispose()


@pytest.fixture()
def session(dao_engine):
    """Function-scoped session with ROLLBACK isolation."""
    connection = dao_engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture()
def patch_dao_session(monkeypatch, session):
    """Make AuditLogDao bind to the test session and replace the v1 schema
    pre-mocks (``resp_200``) with passthroughs so service-layer tests can
    introspect the response. The real ``bypass_tenant_filter`` is a no-op
    against this raw SQLite engine (no event hooks wired here), but we
    still stub it to ``nullcontext`` to keep the call site honest.
    """
    @contextmanager
    def _fake_get_sync():
        yield session

    monkeypatch.setattr(
        'bisheng.database.models.audit_log.get_sync_db_session',
        _fake_get_sync,
    )
    monkeypatch.setattr(
        'bisheng.database.models.audit_log.bypass_tenant_filter',
        lambda: nullcontext(),
    )
    monkeypatch.setattr(
        'bisheng.api.services.audit_log.resp_200',
        lambda data=None: {'data': data},
    )


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _insert_audit(session, *, action, tenant_id, operator_tenant_id,
                  operator_id=None, operator_name=None):
    entry = AuditLog(
        operator_id=operator_id if operator_id is not None else (operator_tenant_id or 0) * 10,
        operator_name=operator_name or f't{operator_tenant_id}-user',
        tenant_id=tenant_id,
        operator_tenant_id=operator_tenant_id,
        action=action,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def _insert_session(session, *, chat_id, tenant_id, user_id=1, flow_type=10):
    """flow_type=10 → ``FlowType.WORKFLOW`` (required for the IN clause)."""
    row = MessageSession(
        chat_id=chat_id,
        flow_id=f'flow-{chat_id}',
        flow_type=flow_type,
        flow_name=f'flow-{chat_id}',
        user_id=user_id,
        tenant_id=tenant_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ===========================================================================
# AuditLogDao.get_audit_logs — system-operations tab
# ===========================================================================

class TestGetAuditLogsTenantScope:

    def _seed(self, session):
        # (1) Root-only: resource & operator both in Root.
        _insert_audit(session, action='root.only', tenant_id=1, operator_tenant_id=1)
        # (2) Child-only: resource & operator both in tenant 2.
        _insert_audit(session, action='child.only', tenant_id=2, operator_tenant_id=2)
        # (3) Cross-op: super (operator_tenant=1) acted on tenant 2's resource.
        _insert_audit(session, action='cross.super_on_child', tenant_id=2, operator_tenant_id=1)
        # (4) Cross-op: child user (operator_tenant=2) touched a Root resource.
        _insert_audit(session, action='cross.child_on_root', tenant_id=1, operator_tenant_id=2)
        # (5) Other-child: tenant 3 — invisible to tenant 2 admin.
        _insert_audit(session, action='other.child', tenant_id=3, operator_tenant_id=3)

    async def test_no_scope_returns_all(self, patch_dao_session, session):
        self._seed(session)

        rows, total = await AuditLogDao.get_audit_logs([])
        actions = {r.action for r in rows}

        assert total == 5
        assert actions == {
            'root.only', 'child.only',
            'cross.super_on_child', 'cross.child_on_root',
            'other.child',
        }

    async def test_child_admin_scope_includes_cross_ops(self, patch_dao_session, session):
        self._seed(session)

        rows, total = await AuditLogDao.get_audit_logs([], tenant_scope=2)
        actions = {r.action for r in rows}

        assert total == 3
        assert actions == {
            'child.only',
            'cross.super_on_child',  # tenant_id=2
            'cross.child_on_root',   # operator_tenant_id=2
        }

    async def test_root_scope_excludes_other_children(self, patch_dao_session, session):
        self._seed(session)

        rows, total = await AuditLogDao.get_audit_logs([], tenant_scope=1)
        actions = {r.action for r in rows}

        assert total == 3
        assert actions == {'root.only', 'cross.super_on_child', 'cross.child_on_root'}

    async def test_pagination_respects_scope(self, patch_dao_session, session):
        for i in range(5):
            _insert_audit(session, action=f'p.{i}', tenant_id=4, operator_tenant_id=4)
        _insert_audit(session, action='other', tenant_id=9, operator_tenant_id=9)

        rows, total = await AuditLogDao.get_audit_logs(
            [], page=1, limit=2, tenant_scope=4,
        )
        assert total == 5
        assert len(rows) == 2
        assert all(r.action.startswith('p.') for r in rows)


# ===========================================================================
# AuditLogDao.get_all_operators — operator filter dropdown
# ===========================================================================

class TestGetAllOperatorsTenantScope:

    def _seed(self, session):
        _insert_audit(
            session, action='r.1', tenant_id=1, operator_tenant_id=1,
            operator_id=100, operator_name='root-admin',
        )
        _insert_audit(
            session, action='c.1', tenant_id=2, operator_tenant_id=2,
            operator_id=200, operator_name='child2-bob',
        )
        _insert_audit(
            session, action='cross', tenant_id=2, operator_tenant_id=1,
            operator_id=100, operator_name='root-admin',
        )
        _insert_audit(
            session, action='c.2', tenant_id=2, operator_tenant_id=2,
            operator_id=201, operator_name='child2-alice',
        )

    def test_no_scope_returns_all_distinct_operators(self, patch_dao_session, session):
        self._seed(session)

        rows = AuditLogDao.get_all_operators([])
        names = {name for _id, name in rows}

        assert names == {'root-admin', 'child2-bob', 'child2-alice'}

    def test_child_admin_scope_includes_cross_op_operator(self, patch_dao_session, session):
        self._seed(session)

        rows = AuditLogDao.get_all_operators([], tenant_scope=2)
        names = {name for _id, name in rows}

        assert names == {'child2-bob', 'child2-alice', 'root-admin'}

    def test_isolated_tenant_hides_other_operators(self, patch_dao_session, session):
        _insert_audit(
            session, action='iso', tenant_id=5, operator_tenant_id=5,
            operator_id=500, operator_name='only-iso',
        )
        _insert_audit(
            session, action='r.x', tenant_id=1, operator_tenant_id=1,
            operator_id=100, operator_name='root-admin',
        )

        rows = AuditLogDao.get_all_operators([], tenant_scope=5)
        names = {name for _id, name in rows}

        assert names == {'only-iso'}


# ===========================================================================
# MessageSession tenant_id predicate — app-usage tab
# ===========================================================================

class TestMessageSessionTenantPredicate:

    def test_scope_filters_root_out(self, session):
        _insert_session(session, chat_id='r1', tenant_id=1, user_id=10)
        _insert_session(session, chat_id='c1', tenant_id=2, user_id=20)
        _insert_session(session, chat_id='c2', tenant_id=2, user_id=21)
        _insert_session(session, chat_id='o1', tenant_id=3, user_id=30)

        conditions = [MessageSession.tenant_id == 2]
        rows = session.exec(
            select(MessageSession).where(and_(*conditions))
        ).all()
        chat_ids = {r.chat_id for r in rows}

        assert chat_ids == {'c1', 'c2'}

    def test_no_scope_is_no_filter(self, session):
        _insert_session(session, chat_id='r1', tenant_id=1, user_id=10)
        _insert_session(session, chat_id='c1', tenant_id=2, user_id=20)

        rows = session.exec(select(MessageSession)).all()
        assert {r.chat_id for r in rows} == {'r1', 'c1'}


# ===========================================================================
# AuditLogService._get_audit_tenant_scope — role matrix
# ===========================================================================

class TestGetAuditTenantScopeHelper:
    """Reads two inputs:
      - ``user.is_global_super`` (JWT-stamped at login by ``init_login_user``)
      - ``get_admin_scope_tenant_id()`` / ``get_current_tenant_id()`` ContextVars
    """

    @pytest.fixture()
    def mock_user(self):
        u = MagicMock()
        u.user_id = 42
        u.is_global_super = False
        return u

    def test_global_super_no_scope_returns_none(self, mock_user):
        mock_user.is_global_super = True
        with patch(
            'bisheng.api.services.audit_log.get_admin_scope_tenant_id',
            return_value=None,
        ), patch(
            'bisheng.api.services.audit_log.get_current_tenant_id',
            return_value=1,
        ):
            scope = AuditLogService._get_audit_tenant_scope(mock_user)

        assert scope is None

    def test_global_super_with_admin_scope_returns_scope(self, mock_user):
        """Super switched management view to tenant 5 → scope to tenant 5."""
        mock_user.is_global_super = True
        with patch(
            'bisheng.api.services.audit_log.get_admin_scope_tenant_id',
            return_value=5,
        ), patch(
            'bisheng.api.services.audit_log.get_current_tenant_id',
            return_value=5,
        ):
            scope = AuditLogService._get_audit_tenant_scope(mock_user)

        assert scope == 5

    def test_child_tenant_admin_returns_leaf(self, mock_user):
        mock_user.is_global_super = False
        with patch(
            'bisheng.api.services.audit_log.get_admin_scope_tenant_id',
            return_value=None,
        ), patch(
            'bisheng.api.services.audit_log.get_current_tenant_id',
            return_value=7,
        ):
            scope = AuditLogService._get_audit_tenant_scope(mock_user)

        assert scope == 7

    def test_non_super_with_log_menu_still_scoped(self, mock_user):
        """Dept admin / log-menu role on tenant 9 still scoped — they
        should never read other tenants' audit data even with the menu.
        """
        mock_user.is_global_super = False
        with patch(
            'bisheng.api.services.audit_log.get_admin_scope_tenant_id',
            return_value=None,
        ), patch(
            'bisheng.api.services.audit_log.get_current_tenant_id',
            return_value=9,
        ):
            scope = AuditLogService._get_audit_tenant_scope(mock_user)

        assert scope == 9


# ===========================================================================
# AuditLogDao.get_audit_logs — multi-filter AND interaction
# ===========================================================================

class TestAuditLogsCombinedFilters:
    """``tenant_scope`` must AND with the existing operator/system/event/time
    filters, never widen visibility.
    """

    async def test_tenant_scope_ands_with_operator_and_system(
        self, patch_dao_session, session,
    ):
        _insert_audit(
            session, action='a.match',
            tenant_id=2, operator_tenant_id=2,
            operator_id=42,
        )
        _insert_audit(
            session, action='a.wrong_operator',
            tenant_id=2, operator_tenant_id=2,
            operator_id=99,
        )
        _insert_audit(
            session, action='a.wrong_tenant',
            tenant_id=3, operator_tenant_id=3,
            operator_id=42,
        )
        keeper = session.exec(
            select(AuditLog).where(AuditLog.action == 'a.match')
        ).one()
        keeper.system_id = 'chat'
        keeper.event_type = 'create_chat'
        session.add(keeper)
        session.commit()

        rows, total = await AuditLogDao.get_audit_logs(
            [],
            operator_ids=[42],
            system_id='chat',
            event_type='create_chat',
            tenant_scope=2,
        )
        assert total == 1
        assert {r.action for r in rows} == {'a.match'}

    async def test_tenant_scope_ands_with_time_window(
        self, patch_dao_session, session,
    ):
        base = datetime(2026, 4, 25, 10, 0, 0)
        for i in range(4):
            entry = AuditLog(
                operator_id=10 + i,
                tenant_id=2,
                operator_tenant_id=2,
                action=f't.{i}',
            )
            session.add(entry)
            session.commit()
            session.refresh(entry)
            entry.create_time = base + timedelta(hours=i)
            session.add(entry)
            session.commit()
        _insert_audit(
            session, action='other_tenant_in_window',
            tenant_id=9, operator_tenant_id=9,
        )

        rows, total = await AuditLogDao.get_audit_logs(
            [],
            start_time=base + timedelta(hours=1),
            end_time=base + timedelta(hours=2, minutes=30),
            tenant_scope=2,
        )
        assert total == 2
        assert {r.action for r in rows} == {'t.1', 't.2'}


# ===========================================================================
# Service-layer end-to-end (system-ops tab)
# ===========================================================================

class TestGetAuditLogServiceEndToEnd:
    """Reproduces the user-reported scenario: a Child Tenant Admin
    (``is_admin()==True`` because of role-based check, but NOT a global
    super) hits ``/api/v1/audit`` and must see ONLY their tenant's rows.
    Pre-fix this path leaked Root rows because the service treated any
    ``is_admin()==True`` as super.
    """

    @pytest.fixture()
    def child_admin(self):
        u = MagicMock()
        u.user_id = 77
        u.is_admin.return_value = True  # AdminRole inside the child tenant
        u.is_global_super = False
        return u

    @pytest.fixture()
    def global_super(self):
        u = MagicMock()
        u.user_id = 1
        u.is_admin.return_value = True
        u.is_global_super = True
        return u

    def _seed_mixed(self, session):
        _insert_audit(
            session, action='r.only',
            tenant_id=1, operator_tenant_id=1,
            operator_id=100, operator_name='root-admin',
        )
        _insert_audit(
            session, action='c.only',
            tenant_id=2, operator_tenant_id=2,
            operator_id=200, operator_name='child2-bob',
        )
        _insert_audit(
            session, action='cross',
            tenant_id=2, operator_tenant_id=1,
            operator_id=100, operator_name='root-admin',
        )

    async def test_child_admin_only_sees_own_tenant(
        self, patch_dao_session, session, child_admin,
    ):
        self._seed_mixed(session)

        with patch(
            'bisheng.api.services.audit_log.get_admin_scope_tenant_id',
            return_value=None,
        ), patch(
            'bisheng.api.services.audit_log.get_current_tenant_id',
            return_value=2,
        ):
            resp = await AuditLogService.get_audit_log(
                child_admin,
                group_ids=[],
                operator_ids=[],
                start_time=None, end_time=None,
                system_id=None, event_type=None,
                page=1, limit=20,
            )

        actions = {row.action for row in resp['data']['data']}
        assert resp['data']['total'] == 2
        assert actions == {'c.only', 'cross'}
        assert 'r.only' not in actions  # the bug we are fixing

    async def test_global_super_sees_everything(
        self, patch_dao_session, session, global_super,
    ):
        self._seed_mixed(session)

        with patch(
            'bisheng.api.services.audit_log.get_admin_scope_tenant_id',
            return_value=None,
        ), patch(
            'bisheng.api.services.audit_log.get_current_tenant_id',
            return_value=1,
        ):
            resp = await AuditLogService.get_audit_log(
                global_super,
                group_ids=[],
                operator_ids=[],
                start_time=None, end_time=None,
                system_id=None, event_type=None,
                page=1, limit=20,
            )

        actions = {row.action for row in resp['data']['data']}
        assert resp['data']['total'] == 3
        assert actions == {'r.only', 'c.only', 'cross'}


# ===========================================================================
# Service-layer end-to-end — operator dropdown
# ===========================================================================

class TestGetAllOperatorsServiceEndToEnd:

    async def test_child_admin_operator_dropdown_excludes_root_only(
        self, patch_dao_session, session,
    ):
        _insert_audit(
            session, action='r.only',
            tenant_id=1, operator_tenant_id=1,
            operator_id=100, operator_name='root-only-admin',
        )
        _insert_audit(
            session, action='c.only',
            tenant_id=2, operator_tenant_id=2,
            operator_id=200, operator_name='child2-bob',
        )

        child_admin = MagicMock()
        child_admin.user_id = 77
        child_admin.is_admin.return_value = True
        child_admin.is_global_super = False

        with patch(
            'bisheng.api.services.audit_log.get_admin_scope_tenant_id',
            return_value=None,
        ), patch(
            'bisheng.api.services.audit_log.get_current_tenant_id',
            return_value=2,
        ):
            ops = await AuditLogService.get_all_operators(child_admin)

        names = {o['user_name'] for o in ops}
        assert names == {'child2-bob'}
        assert 'root-only-admin' not in names


# ===========================================================================
# Service-layer end-to-end — app-usage tab + export inheritance
# ===========================================================================

def _patch_session_dao_helpers(monkeypatch, session):
    """Shared helper used by both the list endpoint and the export endpoint
    fixtures. The export fixture additionally patches ``ChatMessageDao``.
    """
    async def _results(statement, page=None, limit=None):
        stmt = statement
        if page and limit:
            stmt = stmt.offset((page - 1) * limit).limit(limit)
        return list(session.exec(stmt).all())

    async def _count(statement):
        stmt = select(func.count()).select_from(statement.subquery())
        return session.exec(stmt).one()

    monkeypatch.setattr(
        'bisheng.api.services.audit_log.MessageSessionDao'
        '.get_statement_results',
        staticmethod(_results),
    )
    monkeypatch.setattr(
        'bisheng.api.services.audit_log.MessageSessionDao'
        '.get_statement_count',
        staticmethod(_count),
    )
    # AppChatList is a MagicMock under the v1.schema premock. Replace it
    # with a passthrough so test assertions can introspect ``.chat_id``.
    monkeypatch.setattr(
        'bisheng.api.services.audit_log.AppChatList',
        _appchat_passthrough,
    )
    # Enrichment lookups → empty lists; we focus on the tenant-scope filter.
    monkeypatch.setattr(
        'bisheng.api.services.audit_log.UserDao.aget_user_by_ids',
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        'bisheng.api.services.audit_log.FlowDao.aget_flow_by_ids',
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        'bisheng.api.services.audit_log.AssistantDao'
        '.aget_assistants_by_ids',
        AsyncMock(return_value=[]),
    )


class TestGetSessionListServiceEndToEnd:
    """Child Tenant Admin (``is_admin()==True``, NOT global super) calls
    ``get_session_list`` — must NOT see Root tenant sessions. Reproduces
    the original screenshot bug.
    """

    @pytest.fixture()
    def patch_session_dao(self, monkeypatch, session):
        _patch_session_dao_helpers(monkeypatch, session)

    async def test_child_admin_only_sees_own_tenant_sessions(
        self, patch_session_dao, session,
    ):
        _insert_session(session, chat_id='r-1', tenant_id=1, user_id=10)
        _insert_session(session, chat_id='c-1', tenant_id=2, user_id=20)
        _insert_session(session, chat_id='c-2', tenant_id=2, user_id=21)

        child_admin = MagicMock()
        child_admin.user_id = 77
        child_admin.is_admin.return_value = True
        child_admin.is_global_super = False
        child_admin.get_user_groups = AsyncMock(return_value=[])

        with patch(
            'bisheng.api.services.audit_log.get_admin_scope_tenant_id',
            return_value=None,
        ), patch(
            'bisheng.api.services.audit_log.get_current_tenant_id',
            return_value=2,
        ):
            rows, total = await AuditLogService.get_session_list(
                child_admin,
                flow_ids=[], user_ids=[], group_ids=[],
                start_date=None, end_date=None,
                feedback=None, sensitive_status=None,
                page=1, page_size=10,
            )

        chat_ids = {r.chat_id for r in rows}
        assert total == 2
        assert chat_ids == {'c-1', 'c-2'}
        assert 'r-1' not in chat_ids  # the original screenshot bug

    async def test_global_super_sees_all_tenant_sessions(
        self, patch_session_dao, session,
    ):
        _insert_session(session, chat_id='r-1', tenant_id=1, user_id=10)
        _insert_session(session, chat_id='c-1', tenant_id=2, user_id=20)

        super_user = MagicMock()
        super_user.user_id = 1
        super_user.is_admin.return_value = True
        super_user.is_global_super = True
        super_user.get_user_groups = AsyncMock(return_value=[])

        with patch(
            'bisheng.api.services.audit_log.get_admin_scope_tenant_id',
            return_value=None,
        ), patch(
            'bisheng.api.services.audit_log.get_current_tenant_id',
            return_value=1,
        ):
            rows, total = await AuditLogService.get_session_list(
                super_user,
                flow_ids=[], user_ids=[], group_ids=[],
                start_date=None, end_date=None,
                feedback=None, sensitive_status=None,
                page=1, page_size=10,
            )

        assert total == 2
        assert {r.chat_id for r in rows} == {'r-1', 'c-1'}

    async def test_admin_scope_override_acts_as_child_admin(
        self, patch_session_dao, session,
    ):
        """Global super with F019 admin-scope=2 should match child admin of 2."""
        _insert_session(session, chat_id='r-1', tenant_id=1, user_id=10)
        _insert_session(session, chat_id='c-1', tenant_id=2, user_id=20)

        super_user = MagicMock()
        super_user.user_id = 1
        super_user.is_admin.return_value = True
        super_user.is_global_super = True
        super_user.get_user_groups = AsyncMock(return_value=[])

        with patch(
            'bisheng.api.services.audit_log.get_admin_scope_tenant_id',
            return_value=2,  # F019 override
        ), patch(
            'bisheng.api.services.audit_log.get_current_tenant_id',
            return_value=2,
        ):
            rows, total = await AuditLogService.get_session_list(
                super_user,
                flow_ids=[], user_ids=[], group_ids=[],
                start_date=None, end_date=None,
                feedback=None, sensitive_status=None,
                page=1, page_size=10,
            )

        assert total == 1
        assert {r.chat_id for r in rows} == {'c-1'}


class TestGetSessionMessagesExportInherits:
    """``get_session_messages`` (the CSV export endpoint backend) reuses
    ``get_session_list`` internally.
    """

    @pytest.fixture()
    def patch_session_dao(self, monkeypatch, session):
        _patch_session_dao_helpers(monkeypatch, session)
        monkeypatch.setattr(
            'bisheng.api.services.audit_log.ChatMessageDao'
            '.get_all_message_by_chat_ids',
            AsyncMock(return_value=[]),
        )

    async def test_export_excludes_root_rows_for_child_admin(
        self, patch_session_dao, session,
    ):
        _insert_session(session, chat_id='r-x', tenant_id=1, user_id=10)
        _insert_session(session, chat_id='c-x1', tenant_id=2, user_id=20)
        _insert_session(session, chat_id='c-x2', tenant_id=2, user_id=21)

        child_admin = MagicMock()
        child_admin.user_id = 77
        child_admin.is_admin.return_value = True
        child_admin.is_global_super = False
        child_admin.get_user_groups = AsyncMock(return_value=[])

        with patch(
            'bisheng.api.services.audit_log.get_admin_scope_tenant_id',
            return_value=None,
        ), patch(
            'bisheng.api.services.audit_log.get_current_tenant_id',
            return_value=2,
        ):
            rows = await AuditLogService.get_session_messages(
                child_admin,
                flow_ids=[], user_ids=[], group_ids=[],
                start_date=None, end_date=None,
                feedback=None, sensitive_status=None,
            )

        chat_ids = {r.chat_id for r in rows}
        assert chat_ids == {'c-x1', 'c-x2'}
        assert 'r-x' not in chat_ids


# ===========================================================================
# group_ids ∧ tenant_scope intersection — group admin scenario
# ===========================================================================

class TestSessionListGroupAndTenantIntersection:
    """A group admin's view is bounded by BOTH the group filter AND the
    tenant filter — never widened.
    """

    def test_group_filter_and_tenant_filter_intersect(self, session):
        # Tenant 2, group 100 — visible.
        _insert_session(session, chat_id='c-grp100', tenant_id=2, user_id=20)
        # Tenant 1 (Root) but same group 100 — must NOT leak.
        _insert_session(session, chat_id='r-grp100', tenant_id=1, user_id=10)
        # Tenant 2, different group — excluded by the group clause.
        _insert_session(session, chat_id='c-grp200', tenant_id=2, user_id=21)
        session.exec(
            text(
                "UPDATE message_session SET group_ids = :gj "
                "WHERE chat_id IN ('c-grp100', 'r-grp100')"
            ).bindparams(gj='[100]')
        )
        session.exec(
            text(
                "UPDATE message_session SET group_ids = :gj "
                "WHERE chat_id = 'c-grp200'"
            ).bindparams(gj='[200]')
        )
        session.commit()

        # SQLite has no ``json_contains``; emulate via raw SQL LIKE on the
        # JSON text. The point of this test is the AND interaction with
        # ``tenant_id``, not ``json_contains`` semantics (production MySQL).
        rows = session.exec(text("""
            SELECT chat_id FROM message_session
            WHERE tenant_id = 2
              AND group_ids LIKE '%100%'
        """)).all()
        chat_ids = {r[0] for r in rows}

        assert chat_ids == {'c-grp100'}
        assert 'r-grp100' not in chat_ids  # tenant filter blocked it
        assert 'c-grp200' not in chat_ids  # group filter blocked it


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _AppChatPassthrough:
    """Stand-in for the v1 ``AppChatList`` schema (MagicMock'd by the
    import-chain pre-mock). Stores all kwargs as attributes so test
    assertions can introspect ``.chat_id`` / ``.flow_name`` / etc.
    """

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _appchat_passthrough(**kwargs):
    return _AppChatPassthrough(**kwargs)
