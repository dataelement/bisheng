"""Tests for Department and UserDepartment ORM models.

Uses a self-contained SQLite engine with Department/UserDepartment/User tables.
Follows the same pattern as test_tenant_dao.py (F001).
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select

from bisheng.database.models.department import (
    Department,
    UserDepartment,
)


@pytest.fixture(scope='module')
def dao_engine():
    """SQLite engine with Department/UserDepartment/User tables."""
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
        # Minimal user table for JOIN queries in get_members
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
    yield engine
    engine.dispose()


@pytest.fixture()
def session(dao_engine):
    """Transactional session that rolls back after each test."""
    connection = dao_engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


def _create_dept(session, dept_id, name, parent_id=None, path='', **kwargs):
    """Helper to create a department and return it."""
    dept = Department(
        dept_id=dept_id, name=name, parent_id=parent_id, path=path, **kwargs,
    )
    session.add(dept)
    session.commit()
    session.refresh(dept)
    return dept


def _create_user(session, user_name):
    """Helper to create a minimal user record."""
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
# Department tests
# =========================================================================

class TestDepartmentModel:

    def test_create_department(self, session):
        dept = _create_dept(session, 'BS@001', 'Engineering')
        assert dept.id is not None
        assert dept.dept_id == 'BS@001'
        assert dept.name == 'Engineering'
        assert dept.source == 'local'
        assert dept.status == 'active'

    def test_dept_id_unique(self, session):
        _create_dept(session, 'BS@dup1', 'First')
        session.add(Department(dept_id='BS@dup1', name='Second'))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_get_children(self, session):
        parent = _create_dept(session, 'BS@p1', 'Parent', path='/1/')
        _create_dept(session, 'BS@c1', 'Child1', parent_id=parent.id, path=f'/1/{parent.id}/')
        _create_dept(session, 'BS@c2', 'Child2', parent_id=parent.id, path=f'/1/{parent.id}/')
        # archived child should not appear
        _create_dept(
            session, 'BS@c3', 'Archived', parent_id=parent.id,
            path=f'/1/{parent.id}/', status='archived',
        )

        children = session.exec(
            select(Department).where(
                Department.parent_id == parent.id,
                Department.status == 'active',
            )
        ).all()
        assert len(children) == 2

    def test_get_subtree(self, session):
        # Tree: A → B → C
        a = _create_dept(session, 'BS@a1', 'A')
        a.path = f'/{a.id}/'
        session.add(a)
        session.commit()

        b = _create_dept(session, 'BS@b1', 'B', parent_id=a.id)
        b.path = f'/{a.id}/{b.id}/'
        session.add(b)
        session.commit()

        c = _create_dept(session, 'BS@c1a', 'C', parent_id=b.id)
        c.path = f'/{a.id}/{b.id}/{c.id}/'
        session.add(c)
        session.commit()

        subtree = session.exec(
            select(Department).where(
                Department.path.like(f'/{a.id}/%'),
                Department.status == 'active',
            )
        ).all()
        # A's path is /{a.id}/, which also starts with /{a.id}/
        ids = {d.id for d in subtree}
        assert a.id in ids
        assert b.id in ids
        assert c.id in ids
        assert len(subtree) == 3

    def test_get_subtree_ids(self, session):
        root = _create_dept(session, 'BS@sid1', 'Root')
        root.path = f'/{root.id}/'
        session.add(root)
        session.commit()

        child = _create_dept(session, 'BS@sid2', 'Child', parent_id=root.id)
        child.path = f'/{root.id}/{child.id}/'
        session.add(child)
        session.commit()

        ids = session.exec(
            select(Department.id).where(
                Department.path.like(f'/{root.id}/%'),
                Department.status == 'active',
            )
        ).all()
        assert set(ids) == {root.id, child.id}

    def test_update_paths_batch(self, session):
        """Batch path update simulating a department move."""
        from sqlalchemy import update as sa_update, func as sa_func

        root = _create_dept(session, 'BS@upb1', 'Root')
        root.path = f'/{root.id}/'
        session.add(root)
        session.commit()

        child = _create_dept(session, 'BS@upb2', 'Child', parent_id=root.id)
        child.path = f'/{root.id}/{child.id}/'
        session.add(child)
        session.commit()

        grandchild = _create_dept(session, 'BS@upb3', 'GrandChild', parent_id=child.id)
        grandchild.path = f'/{root.id}/{child.id}/{grandchild.id}/'
        session.add(grandchild)
        session.commit()

        # Simulate moving child subtree: old_prefix → new_prefix
        old_prefix = f'/{root.id}/{child.id}/'
        new_prefix = f'/99/{child.id}/'

        session.execute(
            sa_update(Department)
            .where(Department.path.like(f'{old_prefix}%'))
            .values(path=sa_func.replace(Department.path, old_prefix, new_prefix))
        )
        session.commit()

        session.refresh(child)
        session.refresh(grandchild)
        assert child.path == new_prefix
        assert grandchild.path == f'/99/{child.id}/{grandchild.id}/'

    def test_check_name_duplicate_true(self, session):
        parent = _create_dept(session, 'BS@nd1', 'Parent')
        _create_dept(session, 'BS@nd2', 'SameName', parent_id=parent.id)

        exists = session.exec(
            select(Department).where(
                Department.parent_id == parent.id,
                Department.name == 'SameName',
                Department.status == 'active',
            )
        ).first()
        assert exists is not None

    def test_check_name_duplicate_false(self, session):
        parent = _create_dept(session, 'BS@ndf1', 'Parent')
        _create_dept(session, 'BS@ndf2', 'DifferentName', parent_id=parent.id)

        exists = session.exec(
            select(Department).where(
                Department.parent_id == parent.id,
                Department.name == 'NonExistent',
                Department.status == 'active',
            )
        ).first()
        assert exists is None

    def test_check_name_duplicate_exclude(self, session):
        """When updating, exclude the department's own ID."""
        parent = _create_dept(session, 'BS@nde1', 'Parent')
        dept = _create_dept(session, 'BS@nde2', 'MyName', parent_id=parent.id)

        # Same name exists, but it's the department itself — should not be duplicate
        exists = session.exec(
            select(Department).where(
                Department.parent_id == parent.id,
                Department.name == 'MyName',
                Department.status == 'active',
                Department.id != dept.id,
            )
        ).first()
        assert exists is None


# =========================================================================
# UserDepartment tests
# =========================================================================

class TestUserDepartmentModel:

    def test_add_member(self, session):
        dept = _create_dept(session, 'BS@m1', 'Dept')
        user_id = _create_user(session, 'member_user1')

        ud = UserDepartment(user_id=user_id, department_id=dept.id)
        session.add(ud)
        session.commit()
        session.refresh(ud)

        assert ud.id is not None
        assert ud.user_id == user_id
        assert ud.department_id == dept.id
        assert ud.is_primary == 1

    def test_add_member_duplicate(self, session):
        dept = _create_dept(session, 'BS@md1', 'Dept')
        user_id = _create_user(session, 'dup_member')

        session.add(UserDepartment(user_id=user_id, department_id=dept.id))
        session.commit()

        session.add(UserDepartment(user_id=user_id, department_id=dept.id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_remove_member(self, session):
        dept = _create_dept(session, 'BS@rm1', 'Dept')
        user_id = _create_user(session, 'rm_user')

        ud = UserDepartment(user_id=user_id, department_id=dept.id)
        session.add(ud)
        session.commit()

        session.delete(ud)
        session.commit()

        result = session.exec(
            select(UserDepartment).where(
                UserDepartment.user_id == user_id,
                UserDepartment.department_id == dept.id,
            )
        ).first()
        assert result is None

    def test_get_members_paged(self, session):
        """Test paginated member query using raw SQL (avoids User model import chain)."""
        dept = _create_dept(session, 'BS@pg1', 'Dept')
        for i in range(3):
            uid = _create_user(session, f'pg_user_{i}')
            session.add(UserDepartment(user_id=uid, department_id=dept.id))
        session.commit()

        # Use raw SQL to simulate the JOIN query the DAO does
        total = session.execute(text(
            'SELECT COUNT(*) FROM user_department ud '
            'JOIN user u ON u.user_id = ud.user_id '
            'WHERE ud.department_id = :dept_id AND u."delete" = 0'
        ), {'dept_id': dept.id}).scalar()
        assert total == 3

        rows = session.execute(text(
            'SELECT ud.user_id, u.user_name FROM user_department ud '
            'JOIN user u ON u.user_id = ud.user_id '
            'WHERE ud.department_id = :dept_id AND u."delete" = 0 '
            'LIMIT 2 OFFSET 0'
        ), {'dept_id': dept.id}).all()
        assert len(rows) == 2

    def test_get_member_count(self, session):
        from sqlalchemy import func as sa_func

        dept = _create_dept(session, 'BS@mc1', 'Dept')
        for i in range(3):
            uid = _create_user(session, f'mc_user_{i}')
            session.add(UserDepartment(user_id=uid, department_id=dept.id))
        session.commit()

        count = session.exec(
            select(sa_func.count(UserDepartment.id)).where(
                UserDepartment.department_id == dept.id,
            )
        ).one()
        assert count == 3

    def test_get_user_departments(self, session):
        d1 = _create_dept(session, 'BS@ud1', 'Dept1')
        d2 = _create_dept(session, 'BS@ud2', 'Dept2')
        uid = _create_user(session, 'multi_dept_user')

        session.add(UserDepartment(user_id=uid, department_id=d1.id, is_primary=1))
        session.add(UserDepartment(user_id=uid, department_id=d2.id, is_primary=0))
        session.commit()

        results = session.exec(
            select(UserDepartment).where(UserDepartment.user_id == uid)
        ).all()
        assert len(results) == 2
        assert {r.department_id for r in results} == {d1.id, d2.id}

    def test_check_member_exists(self, session):
        dept = _create_dept(session, 'BS@ex1', 'Dept')
        uid = _create_user(session, 'exists_user')

        # Not a member yet
        result = session.exec(
            select(UserDepartment).where(
                UserDepartment.user_id == uid,
                UserDepartment.department_id == dept.id,
            )
        ).first()
        assert result is None

        # Add as member
        session.add(UserDepartment(user_id=uid, department_id=dept.id))
        session.commit()

        result = session.exec(
            select(UserDepartment).where(
                UserDepartment.user_id == uid,
                UserDepartment.department_id == dept.id,
            )
        ).first()
        assert result is not None


# =========================================================================
# v2.5.1 F011: tenant mount point tests
# =========================================================================

class TestTenantMountFields:

    def test_defaults_are_unmounted(self, session):
        dept = _create_dept(session, 'F011@1', 'Dept')
        assert dept.is_tenant_root == 0
        assert dept.mounted_tenant_id is None

    def test_mount_persists(self, session):
        dept = _create_dept(session, 'F011@2', 'Dept')
        dept.is_tenant_root = 1
        dept.mounted_tenant_id = 42
        session.add(dept)
        session.commit()
        session.refresh(dept)

        fetched = session.exec(
            select(Department).where(Department.id == dept.id)
        ).one()
        assert fetched.is_tenant_root == 1
        assert fetched.mounted_tenant_id == 42

    def test_aget_mount_point_select_semantics(self, session):
        """Equivalent SELECT for DAO.aget_mount_point — only marked depts."""
        marked = _create_dept(session, 'F011@3', 'Marked')
        marked.is_tenant_root = 1
        marked.mounted_tenant_id = 7
        unmarked = _create_dept(session, 'F011@4', 'Unmarked')
        session.add_all([marked, unmarked])
        session.commit()

        # DAO.aget_mount_point matches WHERE id=X AND is_tenant_root=1
        for dept_id in (marked.id, unmarked.id):
            result = session.exec(
                select(Department).where(
                    Department.id == dept_id,
                    Department.is_tenant_root == 1,
                )
            ).first()
            if dept_id == marked.id:
                assert result is not None
                assert result.mounted_tenant_id == 7
            else:
                assert result is None

    def test_nearest_ancestor_select_semantics(self, session):
        """Equivalent SELECT for DAO.aget_ancestors_with_mount — path walk."""
        # Tree: A(id=10, mount) → B(id=20, /10/20/) → C(id=30, /10/20/30/)
        a = _create_dept(session, 'A', 'A', path='/10/', sort_order=0)
        # Force ids for deterministic path.
        a.is_tenant_root = 1
        a.mounted_tenant_id = 77
        session.add(a)
        session.commit()

        # For testing ancestor walk we construct candidate_ids from the path
        # of the leaf then SELECT only those marked as mount points.
        leaf_path = f'/{a.id}/something-inner/'
        candidate_ids = [
            int(p) for p in leaf_path.split('/') if p and p.isdigit()
        ]
        result = session.exec(
            select(Department).where(
                Department.id.in_(candidate_ids),
                Department.is_tenant_root == 1,
            ).order_by(func.length(Department.path).desc()).limit(1)
        ).first()
        assert result is not None
        assert result.id == a.id
        assert result.mounted_tenant_id == 77

    def test_no_ancestor_mount_returns_none(self, session):
        """When no ancestor is marked, the walk yields nothing."""
        dept = _create_dept(session, 'Z@1', 'Z', path='/100/200/')
        result = session.exec(
            select(Department).where(
                Department.id.in_([100, 200, dept.id]),
                Department.is_tenant_root == 1,
            ).limit(1)
        ).first()
        assert result is None


# Import guard so func is available in the test above.
from sqlalchemy import func  # noqa: E402
