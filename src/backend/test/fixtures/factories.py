"""Test data factory functions.

Pure functions that insert records via raw SQL and return dicts.
Using raw SQL (not ORM models) avoids import chain issues with
production SQLModel classes.

Usage:
    def test_something(db_session):
        tenant = create_tenant(db_session, code='acme', name='ACME Corp')
        user = create_test_user(db_session, user_name='alice', tenant_id=tenant['id'])
        ...

Created by F000-test-infrastructure.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session


def create_tenant(
    session: Session,
    code: str = 'test',
    name: str = 'Test Tenant',
    status: str = 'active',
    **kwargs,
) -> dict:
    """Insert a tenant record and return it as a dict (including generated id)."""
    extra_cols = ''.join(f', {k}' for k in kwargs)
    extra_vals = ''.join(f', :{k}' for k in kwargs)
    params = {'code': code, 'name': name, 'status': status, **kwargs}

    session.execute(text(
        f'INSERT INTO tenant (tenant_code, tenant_name, status{extra_cols}) '
        f'VALUES (:code, :name, :status{extra_vals})'
    ), params)
    session.flush()

    row = session.execute(
        text('SELECT * FROM tenant WHERE tenant_code = :code'),
        {'code': code},
    ).mappings().one()
    return dict(row)


def create_user_tenant(
    session: Session,
    user_id: int,
    tenant_id: int,
    is_default: int = 1,
) -> dict:
    """Insert a user_tenant association and return it as a dict."""
    session.execute(text(
        'INSERT INTO user_tenant (user_id, tenant_id, is_default) '
        'VALUES (:uid, :tid, :default)'
    ), {'uid': user_id, 'tid': tenant_id, 'default': is_default})
    session.flush()

    row = session.execute(
        text('SELECT * FROM user_tenant WHERE user_id = :uid AND tenant_id = :tid'),
        {'uid': user_id, 'tid': tenant_id},
    ).mappings().one()
    return dict(row)


def create_test_user(
    session: Session,
    user_name: str = 'testuser',
    password: str = 'hashed_password',
    **kwargs,
) -> dict:
    """Insert a user record and return it as a dict."""
    extra_cols = ''.join(f', {k}' for k in kwargs)
    extra_vals = ''.join(f', :{k}' for k in kwargs)
    params = {'user_name': user_name, 'password': password, **kwargs}

    session.execute(text(
        f'INSERT INTO user (user_name, password{extra_cols}) '
        f'VALUES (:user_name, :password{extra_vals})'
    ), params)
    session.flush()

    row = session.execute(
        text('SELECT * FROM user WHERE user_name = :user_name'),
        {'user_name': user_name},
    ).mappings().one()
    return dict(row)


def create_department(
    session: Session,
    dept_id: str = 'BS@test1',
    name: str = 'Test Dept',
    tenant_id: int = 1,
    parent_id: int = None,
    path: str = '',
    **kwargs,
) -> dict:
    """Insert a department record and return it as a dict."""
    cols = 'dept_id, name, tenant_id, path'
    vals = ':dept_id, :name, :tenant_id, :path'
    params = {
        'dept_id': dept_id, 'name': name,
        'tenant_id': tenant_id, 'path': path,
    }
    if parent_id is not None:
        cols += ', parent_id'
        vals += ', :parent_id'
        params['parent_id'] = parent_id

    for k, v in kwargs.items():
        cols += f', {k}'
        vals += f', :{k}'
        params[k] = v

    session.execute(text(
        f'INSERT INTO department ({cols}) VALUES ({vals})'
    ), params)
    session.flush()

    row = session.execute(
        text('SELECT * FROM department WHERE dept_id = :dept_id'),
        {'dept_id': dept_id},
    ).mappings().one()
    return dict(row)


def create_group(
    session: Session,
    group_name: str = 'Test Group',
    tenant_id: int = 1,
    visibility: str = 'public',
    create_user: int = 1,
    **kwargs,
) -> dict:
    """Insert a group record and return it as a dict."""
    extra_cols = ''.join(f', {k}' for k in kwargs)
    extra_vals = ''.join(f', :{k}' for k in kwargs)
    params = {
        'group_name': group_name, 'tenant_id': tenant_id,
        'visibility': visibility, 'create_user': create_user,
        **kwargs,
    }

    session.execute(text(
        f'INSERT INTO "group" (group_name, tenant_id, visibility, create_user{extra_cols}) '
        f'VALUES (:group_name, :tenant_id, :visibility, :create_user{extra_vals})'
    ), params)
    session.flush()

    row = session.execute(
        text('SELECT * FROM "group" WHERE group_name = :gn AND tenant_id = :tid'),
        {'gn': group_name, 'tid': tenant_id},
    ).mappings().one()
    return dict(row)


def create_user_group_member(
    session: Session,
    user_id: int,
    group_id: int,
    is_group_admin: int = 0,
    tenant_id: int = 1,
) -> dict:
    """Insert a usergroup association and return it as a dict."""
    session.execute(text(
        'INSERT INTO usergroup (user_id, group_id, is_group_admin, tenant_id) '
        'VALUES (:uid, :gid, :admin, :tid)'
    ), {'uid': user_id, 'gid': group_id, 'admin': is_group_admin, 'tid': tenant_id})
    session.flush()

    row = session.execute(
        text('SELECT * FROM usergroup WHERE user_id = :uid AND group_id = :gid AND is_group_admin = :admin'),
        {'uid': user_id, 'gid': group_id, 'admin': is_group_admin},
    ).mappings().one()
    return dict(row)


def create_user_department(
    session: Session,
    user_id: int,
    department_id: int,
    is_primary: int = 1,
    source: str = 'local',
) -> dict:
    """Insert a user_department association and return it as a dict."""
    session.execute(text(
        'INSERT INTO user_department (user_id, department_id, is_primary, source) '
        'VALUES (:uid, :did, :primary, :source)'
    ), {'uid': user_id, 'did': department_id, 'primary': is_primary, 'source': source})
    session.flush()

    row = session.execute(
        text('SELECT * FROM user_department WHERE user_id = :uid AND department_id = :did'),
        {'uid': user_id, 'did': department_id},
    ).mappings().one()
    return dict(row)
