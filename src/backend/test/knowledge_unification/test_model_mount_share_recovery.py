"""An already-mounted child only resumes an actual unfinished same command."""

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.tenant_tree import TenantTreeMountConflictError
from bisheng.core.context.tenant import management_tenant_scope
from bisheng.database.models import department as department_module
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.application.model_mount_sharing import ModelMountSharingApplication
from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService, default_tenant_code
from test.knowledge_unification import test_model_delete_plan_application as actual
from test.knowledge_unification import test_model_deletion_application as native_business
from test.knowledge_unification.test_model_provider_sharing_writers import (
    install_sharing,
)

business = native_business.business
impact = actual.impact
model_owner_tenant = actual.model_owner_tenant
ready = actual.ready
removal_session = actual.removal_session


async def test_only_real_unfinished_original_mount_share_can_bypass_already_mounted_conflict(business, monkeypatch):
    factory, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    mounted = ModelMountSharingApplication(share)
    monkeypatch.setattr(department_module, "get_async_db_session", factory)
    async with factory() as session:
        async with session.begin():
            await session.run_sync(lambda current: Department.__table__.create(current.connection(), checkfirst=True))
            session.add(
                Department(
                    id=98,
                    dept_id="native-mount",
                    name="child mount",
                    parent_id=1,
                    tenant_id=1,
                    is_tenant_root=1,
                    mounted_tenant_id=101,
                )
            )
            await session.execute(
                sa.update(Tenant)
                .where(Tenant.id == 101)
                .values(
                    root_dept_id=98,
                    tenant_code=default_tenant_code(98),
                    tenant_name="Original child name",
                )
            )
    parameters = {
        "root_dept_id": 98,
        "child_id": 101,
        "tenant_code": default_tenant_code(98),
        "tenant_name": "Original child name",
        "auto_distribute": True,
    }
    original = share._permission

    async def unavailable(*args, **kwargs):
        raise ConnectionError("sharing preparation transport unavailable")

    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        user.is_global_super = True
        actual.web(user)
        with pytest.raises(TenantTreeMountConflictError):
            await TenantMountService.mount_child(98, None, "Original child name", user)
        monkeypatch.setattr(share, "_permission", unavailable)
        with pytest.raises(ConnectionError):
            await mounted.ashare(identity=user, server_id=2, **parameters)
        assert not client.writes
        with pytest.raises(TenantTreeMountConflictError):
            await TenantMountService.mount_child(98, None, "Different request name", user)
        monkeypatch.setattr(share, "_permission", original)
        user.token_version = 4
        user._runtime_credential_reference = {**user._runtime_credential_reference, "token_version": 4}
        child = await TenantMountService.mount_child(98, None, "Original child name", user)
        assert child.id == 101 and client.rows == {("tenant:101", "shared_with", "llm_server:2")}
        with pytest.raises(TenantTreeMountConflictError):
            await TenantMountService.mount_child(98, None, "Original child name", user)
        async with factory() as session:
            assert len((await session.execute(sa.select(Tenant))).scalars().all()) == 3
            rows = (await session.execute(sa.select(KnowledgeOperationPlan))).scalars().all()
            assert len(rows) == 1 and rows[0].model_execution_state == "COMPLETED"
