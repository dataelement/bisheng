"""覆盖 AC: AC-01, AC-10, AC-11。"""

import pytest
from sqlmodel import select

from bisheng.common.errcode.sso_sync import KunlianBindingConflictError
from bisheng.database.models.department import Department
from test.fixtures import kunlian_onboarding

onboarding_store = kunlian_onboarding.onboarding_store


async def test_anchor_requires_active_root_and_never_claims_existing_node(onboarding_store):
    from bisheng.department.application.external_tenant_anchor import ensure_external_tenant_anchor

    async with onboarding_store.sessions() as session:
        async with session.begin():
            with pytest.raises(KunlianBindingConflictError):
                await ensure_external_tenant_anchor(
                    session, root_department_id=999, local_tenant_id=7, source_key="a" * 64, display_name="fixture"
                )
            first = await ensure_external_tenant_anchor(
                session, root_department_id=1, local_tenant_id=7, source_key="a" * 64, display_name="fixture"
            )
            assert first > 1
    async with onboarding_store.sessions() as session:
        rows = (await session.exec(select(Department).where(Department.id == first))).all()
        assert rows[0].parent_id == 1 and rows[0].tenant_id == 1
        assert rows[0].is_tenant_root == 1 and rows[0].mounted_tenant_id == 7
        async with session.begin_nested():
            with pytest.raises(KunlianBindingConflictError):
                await ensure_external_tenant_anchor(
                    session, root_department_id=1, local_tenant_id=8, source_key="a" * 64, display_name="fixture"
                )
