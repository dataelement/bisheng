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
