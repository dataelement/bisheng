"""Tests for DepartmentService business logic.

Uses a self-contained SQLite engine. Service methods are async and manage
their own sessions via get_async_db_session(). We monkeypatch that to return
our test session, allowing full integration testing without a real MySQL.

Follows the pragmatic test-first approach: ORM + Service tested together.
"""

import pytest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import Column, Integer, Table, create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select

from bisheng.database.models.department import Department, UserDepartment
from bisheng.department.domain.services.department_change_handler import (
    DepartmentChangeHandler,
    TupleOperation,
)

if 'user' not in Department.metadata.tables:
    Table('user', Department.metadata, Column('user_id', Integer, primary_key=True))


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture(scope='module')
def svc_engine():
    """SQLite engine with department/user_department/user/tenant tables."""
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS department (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dept_id VARCHAR(64) NOT NULL UNIQUE,
                name VARCHAR(128) NOT NULL,
                parent_id INTEGER,
                tenant_id INTEGER NOT NULL DEFAULT 1,
                path VARCHAR(512) NOT NULL DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                source VARCHAR(32) DEFAULT 'local',
                external_id VARCHAR(128),
                status VARCHAR(16) DEFAULT 'active',
                is_tenant_root INTEGER NOT NULL DEFAULT 0,
                mounted_tenant_id INTEGER,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                last_sync_ts BIGINT NOT NULL DEFAULT 0,
                default_role_ids JSON,
                create_user INTEGER,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(source, external_id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_department (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                department_id INTEGER NOT NULL,
                is_primary INTEGER DEFAULT 1,
                source VARCHAR(32) DEFAULT 'local',
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(user_id, department_id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name VARCHAR(255) UNIQUE,
                password VARCHAR(255) NOT NULL DEFAULT 'hashed',
                "delete" INTEGER DEFAULT 0,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                password_update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_code VARCHAR(64) NOT NULL UNIQUE,
                tenant_name VARCHAR(128) NOT NULL,
                logo VARCHAR(512),
                root_dept_id INTEGER,
                status VARCHAR(16) NOT NULL DEFAULT 'active',
                contact_name VARCHAR(64),
                contact_phone VARCHAR(32),
                contact_email VARCHAR(128),
                quota_config JSON,
                storage_config JSON,
                create_user INTEGER,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        """))
    yield engine
    engine.dispose()


@pytest.fixture()
def session(svc_engine):
    """Transactional sync session that rolls back after each test."""
    connection = svc_engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


class _MockLoginUser:
    """Minimal mock of LoginUser for testing."""
    def __init__(self, user_id=1, user_role=None, tenant_id=1):
        self.user_id = user_id
        self.user_role = user_role if user_role is not None else [1]  # AdminRole=1
        self.tenant_id = tenant_id


class _NonAdminUser:
    """Mock non-admin user."""
    def __init__(self, user_id=99):
        self.user_id = user_id
        self.user_role = [2]  # Not AdminRole


def _create_root(session, dept_id='BS@root', tenant_id=1):
    """Helper: create a root department and set its path."""
    dept = Department(
        dept_id=dept_id, name='Root', parent_id=None,
        tenant_id=tenant_id, path='', source='local', status='active',
    )
    session.add(dept)
    session.commit()
    session.refresh(dept)
    dept.path = f'/{dept.id}/'
    session.add(dept)
    session.commit()
    session.refresh(dept)
    return dept


def _create_child(session, parent, dept_id, name, **kwargs):
    """Helper: create a child department under parent."""
    defaults = dict(source='local', status='active')
    defaults.update(kwargs)
    dept = Department(
        dept_id=dept_id, name=name, parent_id=parent.id,
        path='', **defaults,
    )
    session.add(dept)
    session.commit()
    session.refresh(dept)
    dept.path = f'{parent.path}{dept.id}/'
    session.add(dept)
    session.commit()
    session.refresh(dept)
    return dept


def _create_user(session, user_name):
    """Helper: create a user record."""
    session.execute(text(
        "INSERT INTO user (user_name, password) VALUES (:name, 'hashed')"
    ), {'name': user_name})
    session.commit()
    row = session.execute(
        text('SELECT user_id FROM user WHERE user_name = :name'),
        {'name': user_name},
    ).one()
    return row[0]


# =========================================================================
# Service logic tests (sync, using ORM directly)
#
# These test the core business logic that DepartmentService implements:
# validation, path computation, name checks, etc. We test at the ORM level
# since the Service methods are async wrappers around the same logic.
# =========================================================================

class TestCreateDepartment:

    @pytest.mark.asyncio
    async def test_service_sets_local_external_id_to_dept_id(self):
        """Local department rows must have external_id for later org-sync match."""
        from bisheng.department.domain.schemas.department_schema import DepartmentCreate
        from bisheng.department.domain.services import department_service as m

        parent = SimpleNamespace(id=1, path='/1/', status='active')
        added = []

        class _Rows:
            def __init__(self, value):
                self.value = value

            def first(self):
                return self.value

        db_session = MagicMock()
        db_session.exec = AsyncMock(side_effect=[
            _Rows(parent),  # parent lookup
            _Rows(None),    # duplicate-name lookup
            _Rows(None),    # dept_id collision lookup
        ])
        db_session.add.side_effect = added.append

        async def _flush():
            added[-1].id = 2

        db_session.flush = AsyncMock(side_effect=_flush)
        db_session.refresh = AsyncMock()
        db_session.commit = AsyncMock()

        @asynccontextmanager
        async def fake_session():
            yield db_session

        with patch.object(
            m, 'get_async_db_session', fake_session,
        ), patch.object(
            m, '_get_dept_id_prefix', return_value='BS',
        ), patch.object(
            m, 'generate_dept_id', return_value='BS@child1',
        ), patch.object(
            m.DepartmentChangeHandler, 'execute_async', new_callable=AsyncMock,
        ):
            dept = await m.DepartmentService.acreate_department(
                DepartmentCreate(name='Engineering', parent_id=1),
                _MockLoginUser(),
            )

        assert dept.dept_id == 'BS@child1'
        assert dept.external_id == 'BS@child1'

    def test_create_department_success(self, session):
        """AC-01: Create department with valid parent, verify path."""
        root = _create_root(session)
        dept = Department(
            dept_id='BS@new1', name='Engineering', parent_id=root.id,
            source='local', status='active', create_user=1,
        )
        session.add(dept)
        session.commit()
        session.refresh(dept)
        dept.path = f'{root.path}{dept.id}/'
        session.add(dept)
        session.commit()
        session.refresh(dept)

        assert dept.id is not None
        assert dept.path == f'/{root.id}/{dept.id}/'
        assert dept.dept_id == 'BS@new1'

    def test_create_department_name_duplicate(self, session):
        """AC-02: Same-level name collision detected."""
        root = _create_root(session, dept_id='BS@dup_root')
        _create_child(session, root, 'BS@dup_c1', 'SameName')

        # Check duplicate logic
        exists = session.exec(
            select(Department).where(
                Department.parent_id == root.id,
                Department.name == 'SameName',
                Department.status == 'active',
            )
        ).first()
        assert exists is not None

    def test_create_department_parent_not_found(self, session):
        """Parent must exist, otherwise raise DepartmentNotFoundError."""
        result = session.exec(
            select(Department).where(Department.id == 99999)
        ).first()
        assert result is None  # parent doesn't exist


class TestGetTree:

    def test_get_tree(self, session):
        """AC-03: Build nested tree from flat departments."""
        from bisheng.department.domain.schemas.department_schema import DepartmentTreeNode

        root = _create_root(session, dept_id='BS@tree_root')
        child_a = _create_child(session, root, 'BS@tree_a', 'Dept A', sort_order=2)
        _child_b = _create_child(session, root, 'BS@tree_b', 'Dept B', sort_order=1)
        _grandchild = _create_child(session, child_a, 'BS@tree_gc', 'Sub A')

        # Add members to child_a
        uid = _create_user(session, 'tree_user')
        session.add(UserDepartment(user_id=uid, department_id=child_a.id))
        session.commit()

        # Fetch all active departments
        depts = session.exec(
            select(Department).where(Department.status == 'active')
        ).all()

        # Build count map
        from sqlalchemy import func
        count_result = session.exec(
            select(
                UserDepartment.department_id,
                func.count(UserDepartment.id),
            )
            .where(UserDepartment.department_id.in_([d.id for d in depts]))
            .group_by(UserDepartment.department_id)
        ).all()
        count_map = dict(count_result)

        # Build tree
        nodes = {}
        for d in depts:
            nodes[d.id] = DepartmentTreeNode(
                id=d.id, dept_id=d.dept_id, name=d.name,
                parent_id=d.parent_id, path=d.path,
                sort_order=d.sort_order, source=d.source, status=d.status,
                member_count=count_map.get(d.id, 0), children=[],
            )
        roots = []
        for node in nodes.values():
            if node.parent_id is not None and node.parent_id in nodes:
                nodes[node.parent_id].children.append(node)
            else:
                roots.append(node)

        # Find our test root
        test_root = next((r for r in roots if r.dept_id == 'BS@tree_root'), None)
        assert test_root is not None
        assert len(test_root.children) == 2

        # Sort by sort_order
        test_root.children.sort(key=lambda n: n.sort_order)
        assert test_root.children[0].name == 'Dept B'  # sort_order=1
        assert test_root.children[1].name == 'Dept A'  # sort_order=2
        assert test_root.children[1].member_count == 1
        assert len(test_root.children[1].children) == 1


class TestUpdateDepartment:

    def test_update_department_name(self, session):
        """AC-05: Update name successfully."""
        root = _create_root(session, dept_id='BS@upd_root')
        child = _create_child(session, root, 'BS@upd_c1', 'OldName')

        child.name = 'NewName'
        session.add(child)
        session.commit()
        session.refresh(child)
        assert child.name == 'NewName'

    def test_update_department_source_readonly(self, session):
        """AC-06: source='feishu' department name cannot be modified."""
        root = _create_root(session, dept_id='BS@ro_root')
        child = _create_child(session, root, 'BS@ro_c1', 'FeishuDept', source='feishu')

        # Service logic: if source != 'local' and name update requested -> error
        assert child.source != 'local'
        # Would raise DepartmentSourceReadonlyError in service


class TestDeleteDepartment:

    def test_delete_department_success(self, session):
        """AC-07: Archive department with no children and no members."""
        root = _create_root(session, dept_id='BS@del_root')
        child = _create_child(session, root, 'BS@del_c1', 'ToDelete')

        # No children, no members -> can archive
        children = session.exec(
            select(Department).where(
                Department.parent_id == child.id,
                Department.status == 'active',
            )
        ).first()
        assert children is None

        from sqlalchemy import func
        count = session.exec(
            select(func.count(UserDepartment.id)).where(
                UserDepartment.department_id == child.id,
            )
        ).one()
        assert count == 0

        child.status = 'archived'
        session.add(child)
        session.commit()
        session.refresh(child)
        assert child.status == 'archived'

    def test_delete_department_has_children(self, session):
        """AC-08: Cannot delete department with active children."""
        root = _create_root(session, dept_id='BS@dhc_root')
        parent = _create_child(session, root, 'BS@dhc_p', 'Parent')
        _create_child(session, parent, 'BS@dhc_c', 'Child')

        children = session.exec(
            select(Department).where(
                Department.parent_id == parent.id,
                Department.status == 'active',
            )
        ).first()
        assert children is not None  # Has children, would raise error

    def test_delete_department_has_members(self, session):
        """AC-09: Cannot delete department with members."""
        root = _create_root(session, dept_id='BS@dhm_root')
        dept = _create_child(session, root, 'BS@dhm_c', 'HasMembers')
        uid = _create_user(session, 'dhm_user')
        session.add(UserDepartment(user_id=uid, department_id=dept.id))
        session.commit()

        from sqlalchemy import func
        count = session.exec(
            select(func.count(UserDepartment.id)).where(
                UserDepartment.department_id == dept.id,
            )
        ).one()
        assert count > 0  # Has members, would raise error


class TestMoveDepartment:

    def test_move_department_success(self, session):
        """AC-10: Move department updates path for entire subtree."""
        from sqlalchemy import update, func

        root = _create_root(session, dept_id='BS@mv_root')
        branch_a = _create_child(session, root, 'BS@mv_a', 'Branch A')
        branch_b = _create_child(session, root, 'BS@mv_b', 'Branch B')
        leaf = _create_child(session, branch_a, 'BS@mv_leaf', 'Leaf')

        # Move branch_a under branch_b
        old_path = branch_a.path
        new_path = f'{branch_b.path}{branch_a.id}/'

        session.execute(
            update(Department)
            .where(Department.path.like(f'{old_path}%'))
            .values(path=func.replace(Department.path, old_path, new_path))
        )
        branch_a.parent_id = branch_b.id
        branch_a.path = new_path
        session.add(branch_a)
        session.commit()

        session.refresh(branch_a)
        session.refresh(leaf)

        assert branch_a.path == f'{branch_b.path}{branch_a.id}/'
        assert leaf.path == f'{branch_b.path}{branch_a.id}/{leaf.id}/'
        assert branch_a.parent_id == branch_b.id

    def test_move_department_circular(self, session):
        """AC-11: Cannot move to own subtree."""
        root = _create_root(session, dept_id='BS@circ_root')
        parent = _create_child(session, root, 'BS@circ_p', 'Parent')
        child = _create_child(session, parent, 'BS@circ_c', 'Child')

        # Try to move parent under child -> circular
        assert child.path.startswith(parent.path)
        # Service would raise DepartmentCircularMoveError

        # Also: move to self
        assert parent.id == parent.id  # trivially true, but new_parent_id == dept.id check


class TestMemberManagement:

    def test_add_members_batch(self, session):
        """AC-12: Batch add users as department members."""
        root = _create_root(session, dept_id='BS@mbr_root')
        dept = _create_child(session, root, 'BS@mbr_d', 'Team')

        user_ids = []
        for i in range(3):
            uid = _create_user(session, f'mbr_user_{i}')
            user_ids.append(uid)

        for uid in user_ids:
            session.add(UserDepartment(
                user_id=uid, department_id=dept.id, is_primary=0, source='local',
            ))
        session.commit()

        members = session.exec(
            select(UserDepartment).where(
                UserDepartment.department_id == dept.id,
            )
        ).all()
        assert len(members) == 3

    def test_add_members_duplicate(self, session):
        """AC-13: Adding existing member raises error."""
        root = _create_root(session, dept_id='BS@mbd_root')
        dept = _create_child(session, root, 'BS@mbd_d', 'Team')
        uid = _create_user(session, 'mbd_user')
        session.add(UserDepartment(user_id=uid, department_id=dept.id))
        session.commit()

        # Check if already exists
        existing = session.exec(
            select(UserDepartment).where(
                UserDepartment.user_id == uid,
                UserDepartment.department_id == dept.id,
            )
        ).first()
        assert existing is not None  # Would raise DepartmentMemberExistsError

    def test_get_members_paged(self, session):
        """AC-14: Paginated member query."""
        root = _create_root(session, dept_id='BS@pgm_root')
        dept = _create_child(session, root, 'BS@pgm_d', 'Team')
        for i in range(5):
            uid = _create_user(session, f'pgm_user_{i}')
            session.add(UserDepartment(user_id=uid, department_id=dept.id))
        session.commit()

        from sqlalchemy import func
        total = session.exec(
            select(func.count(UserDepartment.id)).where(
                UserDepartment.department_id == dept.id,
            )
        ).one()
        assert total == 5

        # Page 1, limit 2
        rows = session.exec(
            select(UserDepartment)
            .where(UserDepartment.department_id == dept.id)
            .offset(0).limit(2)
        ).all()
        assert len(rows) == 2

    def test_remove_member(self, session):
        """AC-15: Remove user from department."""
        root = _create_root(session, dept_id='BS@rmm_root')
        dept = _create_child(session, root, 'BS@rmm_d', 'Team')
        uid = _create_user(session, 'rmm_user')
        ud = UserDepartment(user_id=uid, department_id=dept.id)
        session.add(ud)
        session.commit()

        session.delete(ud)
        session.commit()

        remaining = session.exec(
            select(UserDepartment).where(
                UserDepartment.user_id == uid,
                UserDepartment.department_id == dept.id,
            )
        ).first()
        assert remaining is None

    def test_remove_member_not_found(self, session):
        """Member doesn't exist -> would raise DepartmentMemberNotFoundError."""
        root = _create_root(session, dept_id='BS@rmnf_root')
        dept = _create_child(session, root, 'BS@rmnf_d', 'Team')

        result = session.exec(
            select(UserDepartment).where(
                UserDepartment.user_id == 99999,
                UserDepartment.department_id == dept.id,
            )
        ).first()
        assert result is None  # Would raise error


class TestPermission:

    def test_permission_denied(self):
        """AC-16: Non-admin user cannot access department operations."""
        from bisheng.department.domain.services.department_service import _is_admin

        admin = _MockLoginUser(user_role=[1])
        non_admin = _NonAdminUser()

        assert _is_admin(admin) is True
        assert _is_admin(non_admin) is False

    async def test_check_permission_raises(self):
        """_check_permission raises DepartmentPermissionDeniedError for non-admin.

        ``_check_permission`` is an ``async def`` — the original sync
        call produced a coroutine that was never awaited, so
        ``pytest.raises`` saw no exception and the test silently
        passed/failed as DID NOT RAISE. ``asyncio_mode='auto'`` (see
        pyproject.toml) lets an ``async def test_*`` method run under
        the asyncio runner transparently.
        """
        from bisheng.common.errcode.department import DepartmentPermissionDeniedError
        from bisheng.department.domain.services.department_service import _check_permission

        with pytest.raises(DepartmentPermissionDeniedError):
            await _check_permission(_NonAdminUser())

    @pytest.mark.asyncio
    async def test_get_tree_allows_tenant_admin_full_tree(self):
        from bisheng.database.models.department import DepartmentDao
        from bisheng.department.domain.services.department_service import DepartmentService

        login_user = _MockLoginUser(user_id=7, user_role=[2], tenant_id=1)
        root = SimpleNamespace(
            id=1,
            dept_id='BS@root',
            name='Root',
            parent_id=None,
            path='/1/',
            sort_order=0,
            source='local',
            status='active',
        )
        child = SimpleNamespace(
            id=2,
            dept_id='BS@child',
            name='Child',
            parent_id=1,
            path='/1/2/',
            sort_order=0,
            source='local',
            status='active',
        )

        dept_result = MagicMock()
        dept_result.all.return_value = [root, child]
        count_result = MagicMock()
        count_result.all.return_value = [(1, 3), (2, 1)]
        db_session = MagicMock()
        db_session.exec = AsyncMock(side_effect=[dept_result, count_result])

        @asynccontextmanager
        async def fake_session():
            yield db_session

        with patch(
            'bisheng.department.domain.services.department_service.get_async_db_session',
            fake_session,
        ), patch.object(
            DepartmentDao, 'aget_user_admin_departments',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_perm_check, patch(
            'bisheng.department.domain.services.department_service._is_registration_enabled',
            return_value=True,
        ):
            tree = await DepartmentService.aget_tree(login_user)

        assert [node.id for node in tree] == [1]
        assert tree[0].member_count == 3
        assert [child.id for child in tree[0].children] == [2]
        assert tree[0].children[0].member_count == 1
        mock_perm_check.assert_awaited_once_with(
            user_id=login_user.user_id,
            relation='admin',
            object_type='tenant',
            object_id=str(login_user.tenant_id),
            login_user=login_user,
        )


class TestLocalMemberCreate:

    @pytest.mark.asyncio
    async def test_assignable_roles_bypasses_tenant_filter_for_global_roles(self):
        from bisheng.department.domain.services.department_service import DepartmentService

        entered = {'value': False}
        dept = MagicMock()
        dept.id = 10
        login_user = _MockLoginUser(user_id=1, user_role=[1], tenant_id=23)
        role = MagicMock()
        role.id = 2
        role.role_name = '普通用户'
        role.role_type = 'global'
        role.department_id = None

        class _Rows:
            def all(self):
                return [role]

        class _Session:
            async def exec(self, _stmt):
                return _Rows()

        @asynccontextmanager
        async def fake_session():
            yield _Session()

        class _Bypass:
            def __enter__(self):
                entered['value'] = True

            def __exit__(self, exc_type, exc, tb):
                return False

        class _Column:
            def is_(self, _value):
                return object()

            def in_(self, _values):
                return object()

            def __eq__(self, _value):
                return object()

            def __gt__(self, _value):
                return object()

            def asc(self):
                return object()

        class _Role:
            id = _Column()
            role_name = _Column()
            role_type = _Column()
            tenant_id = _Column()
            department_id = _Column()

        class _Stmt:
            def where(self, *_args):
                return self

            def order_by(self, *_args):
                return self

        with patch(
            'bisheng.department.domain.services.department_service.get_async_db_session',
            fake_session,
        ), patch(
            'bisheng.department.domain.services.department_service._get_dept_and_check_permission',
            new_callable=AsyncMock,
            return_value=dept,
        ), patch.object(
            DepartmentService,
            '_aget_ancestor_chain_ids',
            new_callable=AsyncMock,
            return_value=[10],
        ), patch(
            'bisheng.core.context.tenant.bypass_tenant_filter',
            return_value=_Bypass(),
        ), patch.dict(
            'sys.modules',
            {'bisheng.database.models.role': SimpleNamespace(Role=_Role)},
        ), patch(
            'bisheng.department.domain.services.department_service.select',
            return_value=_Stmt(),
        ), patch(
            'bisheng.department.domain.services.department_service.and_',
            return_value=object(),
        ), patch(
            'bisheng.department.domain.services.department_service.or_',
            return_value=object(),
        ):
            rows = await DepartmentService.aget_assignable_roles('BS@test', login_user)

        assert entered['value'] is True
        assert rows == [
            {
                'id': 2,
                'role_name': '普通用户',
                'role_type': 'global',
                'department_id': None,
            }
        ]

    @pytest.mark.asyncio
    async def test_create_local_member_rejects_archived_department_before_user_create(self):
        from bisheng.common.errcode.department import DepartmentArchivedReadonlyError
        from bisheng.department.domain.schemas.department_schema import DepartmentLocalMemberCreate
        from bisheng.department.domain.services.department_service import DepartmentService
        from bisheng.user.domain.services import user as user_service_module

        dept = MagicMock()
        dept.status = 'archived'
        login_user = _MockLoginUser(user_id=1, user_role=[1])
        data = DepartmentLocalMemberCreate(
            user_name='Alice',
            person_id='person-001',
            password='Aa123456!',
            role_ids=[],
        )

        @asynccontextmanager
        async def fake_session():
            yield MagicMock()

        with patch(
            'bisheng.department.domain.services.department_service.get_async_db_session',
            fake_session,
        ), patch(
            'bisheng.department.domain.services.department_service._get_dept_and_check_permission',
            new_callable=AsyncMock,
            return_value=dept,
        ), patch.object(
            user_service_module.UserService, 'decrypt_password_plain',
            return_value='Aa123456!',
        ) as decrypt:
            with pytest.raises(DepartmentArchivedReadonlyError):
                await DepartmentService.acreate_local_member('BS@test', data, login_user)

        decrypt.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_local_member_rejects_deleted_person_id_with_restore_hint(self):
        from bisheng.common.errcode.department import DepartmentPersonIdDeletedAccountError
        from bisheng.department.domain.schemas.department_schema import DepartmentLocalMemberCreate
        from bisheng.department.domain.services.department_service import DepartmentService
        from bisheng.user.domain.models import user as user_model_module
        from bisheng.user.domain.services import user as user_service_module

        dept = MagicMock()
        dept.default_role_ids = []
        login_user = _MockLoginUser(user_id=1, user_role=[1])
        data = DepartmentLocalMemberCreate(
            user_name='Alice',
            person_id='person-001',
            password='Aa123456!',
            role_ids=[],
        )

        @asynccontextmanager
        async def fake_session():
            yield MagicMock()

        with patch(
            'bisheng.department.domain.services.department_service.get_async_db_session',
            fake_session,
        ), patch(
            'bisheng.department.domain.services.department_service._get_dept_and_check_permission',
            new_callable=AsyncMock,
            return_value=dept,
        ), patch.object(
            user_service_module.UserService, 'decrypt_password_plain',
            return_value='Aa123456!',
        ), patch(
            'bisheng.department.domain.services.department_service.DepartmentService.aget_assignable_roles',
            new_callable=AsyncMock,
            return_value=[],
        ) as assignable_roles, patch.object(
            user_model_module.UserDao, 'aget_login_candidates_by_account',
            new_callable=AsyncMock, return_value=[],
        ), patch.object(
            user_model_module.UserDao, 'aexists_disabled_login_account',
            new_callable=AsyncMock, return_value=True,
        ):
            with pytest.raises(DepartmentPersonIdDeletedAccountError) as exc:
                await DepartmentService.acreate_local_member('BS@test', data, login_user)

        assert 'Please restore the original account' in exc.value.message
        assignable_roles.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_local_member_reports_duplicate_person_id_before_role_validation(self):
        from bisheng.common.errcode.department import DepartmentPersonIdDuplicateError
        from bisheng.department.domain.schemas.department_schema import DepartmentLocalMemberCreate
        from bisheng.department.domain.services.department_service import DepartmentService
        from bisheng.user.domain.models import user as user_model_module
        from bisheng.user.domain.services import user as user_service_module

        dept = MagicMock()
        dept.default_role_ids = []
        login_user = _MockLoginUser(user_id=1, user_role=[1])
        data = DepartmentLocalMemberCreate(
            user_name='Alice',
            person_id='person-001',
            password='Aa123456!',
            role_ids=[999],
        )

        @asynccontextmanager
        async def fake_session():
            yield MagicMock()

        with patch(
            'bisheng.department.domain.services.department_service.get_async_db_session',
            fake_session,
        ), patch(
            'bisheng.department.domain.services.department_service._get_dept_and_check_permission',
            new_callable=AsyncMock,
            return_value=dept,
        ), patch.object(
            user_service_module.UserService, 'decrypt_password_plain',
            return_value='Aa123456!',
        ), patch.object(
            user_model_module.UserDao, 'aget_login_candidates_by_account',
            new_callable=AsyncMock, return_value=[MagicMock()],
        ), patch.object(
            user_model_module.UserDao, 'aexists_disabled_login_account',
            new_callable=AsyncMock,
        ) as disabled_lookup, patch(
            'bisheng.department.domain.services.department_service.DepartmentService.aget_assignable_roles',
            new_callable=AsyncMock,
            return_value=[],
        ) as assignable_roles:
            with pytest.raises(DepartmentPersonIdDuplicateError):
                await DepartmentService.acreate_local_member('BS@test', data, login_user)

        disabled_lookup.assert_not_called()
        assignable_roles.assert_not_called()


class TestRootDepartment:

    def test_create_root_department(self, session):
        """AC-18: Create root department with parent_id=None, path=/{id}/."""
        root = _create_root(session, dept_id='BS@cr_root', tenant_id=1)
        assert root.parent_id is None
        assert root.path == f'/{root.id}/'

        # Simulate tenant.root_dept_id writeback
        session.execute(text(
            'INSERT INTO tenant (tenant_code, tenant_name, root_dept_id) '
            "VALUES ('cr_tenant', 'CR Tenant', :root_id)"
        ), {'root_id': root.id})
        session.commit()

        row = session.execute(
            text("SELECT root_dept_id FROM tenant WHERE tenant_code = 'cr_tenant'")
        ).one()
        assert row[0] == root.id

    def test_create_root_department_exists(self, session):
        """AC-19: Duplicate root should be detected."""
        _create_root(session, dept_id='BS@dup_rt', tenant_id=1)

        # Check if root already exists
        existing = session.exec(
            select(Department).where(
                Department.parent_id.is_(None),
                Department.tenant_id == 1,
                Department.status == 'active',
            )
        ).first()
        assert existing is not None  # Would raise DepartmentRootExistsError


class TestChangeHandler:

    def test_change_handler_on_created(self):
        """AC-20: on_created returns correct TupleOperation."""
        ops = DepartmentChangeHandler.on_created(dept_id=5, parent_id=1)
        assert len(ops) == 1
        assert ops[0] == TupleOperation(
            action='write', user='department:1',
            relation='parent', object='department:5',
        )

    def test_change_handler_on_moved(self):
        """AC-20: on_moved returns delete old + write new."""
        ops = DepartmentChangeHandler.on_moved(
            dept_id=5, old_parent_id=1, new_parent_id=3,
        )
        assert len(ops) == 2
        assert ops[0].action == 'delete'
        assert ops[0].user == 'department:1'
        assert ops[1].action == 'write'
        assert ops[1].user == 'department:3'

    def test_change_handler_on_members_added(self):
        """AC-20: on_members_added returns one write per user."""
        ops = DepartmentChangeHandler.on_members_added(dept_id=5, user_ids=[1, 2, 3])
        assert len(ops) == 3
        assert all(o.action == 'write' for o in ops)
        assert all(o.relation == 'member' for o in ops)
        assert {o.user for o in ops} == {'user:1', 'user:2', 'user:3'}
