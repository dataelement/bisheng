"""AC-57: real SQL finds misplaced children without rewriting history."""

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.role import Role
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.permission.domain.models.grant import PermissionGrant, PermissionGrantAssignee
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.tenant.domain.repositories import context_preflight
from test.fixtures.managed_tenant import managed_db as managed_db
from test.role.test_effective_roles import policy_db as policy_db


async def test_inventory_preserves_legacy_owners_and_detects_wrong_children(policy_db, monkeypatch):
    await policy_db.create(
        Flow,
        FlowVersion,
        Knowledge,
        KnowledgeFile,
        PermissionGrant,
        PermissionGrantAssignee,
        BusinessResourceReference,
        TenantSystemModelConfig,
    )
    monkeypatch.setattr(context_preflight, "get_async_db_session", policy_db.sessions)
    with bypass_tenant_filter():
        async with policy_db.sessions() as s:
            s.add_all(
                [
                    Flow(id="scope-check", name="A", tenant_id=2, user_id=1, flow_type=10),
                    FlowVersion(id=991, flow_id="scope-check", name="v0", tenant_id=3),
                    BusinessResourceReference(
                        id=991,
                        tenant_id=2,
                        source_type="workflow_version",
                        source_id="scope-check",
                        source_version="991",
                        slot_key="llm",
                        target_type="model",
                        target_id="13",
                        target_tenant_id=1,
                        source_revision=1,
                    ),
                    PermissionGrant(
                        id=991, tenant_id=3, resource_type="workflow", resource_id="scope-check", model_key="read"
                    ),
                    Role(id=901, role_name="legacy-shared", role_type="global", tenant_id=3),
                    RoleAccess(id=991, role_id=901, type=AccessType.WEB_MENU.value, third_id="build", tenant_id=2),
                ]
            )
            await s.commit()
    report = await context_preflight.TenantContextPreflightRepository.inventory(2, limit=100)
    assert report["read_only"] is True and report["historical_compatibility_verified"] is False
    assert any(r["kind"] == "versions" and r["issue"] == "OWNER_MISMATCH" for r in report["findings"])
    assert any(r["kind"] == "menus" and r["issue"] == "OWNER_MISMATCH" for r in report["findings"])
    assert report["sql_inventory"]["references"][0]["scope_relation"] == "CROSS_SCOPE_REQUIRES_DOMAIN_PROOF"
    assert any(r["kind"] == "workflow_grants" and r["issue"] == "OWNER_MISMATCH" for r in report["findings"])
    with bypass_tenant_filter():
        async with policy_db.sessions() as s:
            assert (await s.exec(select(FlowVersion).where(FlowVersion.id == 991))).one().tenant_id == 3
            assert (await s.exec(select(Role).where(Role.id == 901))).one().tenant_id == 3
    page = await context_preflight.TenantContextPreflightRepository.inventory(2, limit=1)
    assert any(page["truncated"].values())
    assert any(v is not None for v in page["next_offsets"].values())
