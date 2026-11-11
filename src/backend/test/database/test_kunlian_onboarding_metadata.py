"""三表发现、租户隔离及回执栅栏约束; 不代表真实数据库验收。"""

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from bisheng.core.context.tenant import strict_tenant_filter, tenant_execution_scope
from bisheng.core.database import tenant_filter
from bisheng.core.database.model_discovery import discover_sqlmodel_module_names
from bisheng.role.domain.models.external_basic_role import RoleExternalBasicRole
from bisheng.tenant.domain.models.external_provision import TenantExternalProvision
from bisheng.user.domain.models.external_basic_access import UserExternalBasicAccess


def test_three_owner_tables_are_discoverable_and_registered_for_filtering():
    modules = {
        "bisheng.tenant.domain.models.external_provision",
        "bisheng.role.domain.models.external_basic_role",
        "bisheng.user.domain.models.external_basic_access",
    }
    assert modules <= set(discover_sqlmodel_module_names())
    assert modules <= set(tenant_filter._TENANT_AWARE_MODEL_MODULES)
    for model in (TenantExternalProvision, RoleExternalBasicRole, UserExternalBasicAccess):
        assert model.__table__.c.tenant_id.index
    assert not RoleExternalBasicRole.__table__.foreign_keys
    assert not UserExternalBasicAccess.__table__.foreign_keys


def test_new_tables_keep_child_rows_separate_and_fence_constraints_durable():
    # 事件注册是全局状态, 在独立解释器验证以免改变其他测试的隔离设置。
    code = (
        "from test.fixtures.mock_services import premock_import_chain; premock_import_chain(); "
        "from test.database.test_kunlian_onboarding_metadata import _assert_tenant_filter_contract; "
        "_assert_tenant_filter_contract()"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _assert_tenant_filter_contract():
    tenant_filter.register_tenant_filter_events()
    engine = create_engine("sqlite://")
    tables = [TenantExternalProvision.__table__, RoleExternalBasicRole.__table__, UserExternalBasicAccess.__table__]
    SQLModel.metadata.create_all(engine, tables=tables)
    try:
        with tenant_execution_scope(1), strict_tenant_filter(), Session(engine) as session:
            session.add(
                TenantExternalProvision(
                    source_key="s" * 64,
                    connection_id="fixture",
                    issuer="https://fixture",
                    issuer_digest="i" * 64,
                    external_tenant_id="A",
                )
            )
            session.commit()
        with tenant_execution_scope(7), strict_tenant_filter(), Session(engine) as session:
            session.add(RoleExternalBasicRole(connection_id="fixture", tenant_id=7, role_id=91))
            session.add(
                UserExternalBasicAccess(connection_id="fixture", identity_key="u" * 64, tenant_id=7, user_id=42)
            )
            session.commit()
            assert len(session.exec(select(RoleExternalBasicRole)).all()) == 1
            assert not session.exec(select(TenantExternalProvision)).all()
        with tenant_execution_scope(8), strict_tenant_filter(), Session(engine) as session:
            assert not session.exec(select(RoleExternalBasicRole)).all()
            assert not session.exec(select(UserExternalBasicAccess)).all()
        with tenant_execution_scope(7), strict_tenant_filter(), Session(engine) as session:
            row = session.exec(select(UserExternalBasicAccess)).one()
            row.applied_fence = 1
            session.add(row)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
    finally:
        engine.dispose()
