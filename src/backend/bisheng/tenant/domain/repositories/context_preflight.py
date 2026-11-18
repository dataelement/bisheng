"""Bounded, read-only relationship facts for management-view rollout."""

from sqlalchemy import and_, or_
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.role import Role
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.database.models.tenant import UserTenant
from bisheng.database.models.user_role import UserRole
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.permission.domain.models.grant import PermissionGrant, PermissionGrantAssignee
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference


class TenantContextPreflightRepository:
    @staticmethod
    async def inventory(tenant_id, *, limit=100, offset=0):
        if type(tenant_id) is not int or tenant_id < 1 or not 1 <= limit <= 1000 or offset < 0:
            raise ValueError("positive tenant and bounded page are required")
        report = {"tenant_id": tenant_id, "read_only": True, "findings": [], "truncated": {}, "next_offsets": {}}
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                bindings = (
                    select(UserRole, Role, UserTenant)
                    .outerjoin(Role, Role.id == UserRole.role_id)
                    .outerjoin(UserTenant, and_(UserTenant.user_id == UserRole.user_id, UserTenant.is_active == 1))
                    .where(or_(UserRole.tenant_id == tenant_id, UserTenant.tenant_id == tenant_id))
                    .order_by(UserRole.user_id, UserRole.role_id, UserRole.tenant_id, UserTenant.tenant_id)
                )
                versions = (
                    select(FlowVersion, Flow)
                    .outerjoin(Flow, Flow.id == FlowVersion.flow_id)
                    .where(or_(FlowVersion.tenant_id == tenant_id, Flow.tenant_id == tenant_id))
                    .order_by(FlowVersion.id)
                )
                files = (
                    select(KnowledgeFile, Knowledge)
                    .outerjoin(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
                    .where(or_(KnowledgeFile.tenant_id == tenant_id, Knowledge.tenant_id == tenant_id))
                    .order_by(KnowledgeFile.id)
                )
                menus = (
                    select(RoleAccess, Role)
                    .outerjoin(Role, Role.id == RoleAccess.role_id)
                    .where(
                        RoleAccess.type == AccessType.WEB_MENU.value,
                        or_(RoleAccess.tenant_id == tenant_id, Role.tenant_id == tenant_id),
                    )
                    .order_by(RoleAccess.id)
                )
                grant_sources = (
                    select(PermissionGrantAssignee, PermissionGrant)
                    .outerjoin(PermissionGrant, PermissionGrant.id == PermissionGrantAssignee.grant_id)
                    .where(or_(PermissionGrantAssignee.tenant_id == tenant_id, PermissionGrant.tenant_id == tenant_id))
                    .order_by(PermissionGrantAssignee.id)
                )
                workflow_grants = (
                    select(PermissionGrant, Flow)
                    .outerjoin(Flow, Flow.id == PermissionGrant.resource_id)
                    .where(
                        PermissionGrant.resource_type == "workflow",
                        or_(PermissionGrant.tenant_id == tenant_id, Flow.tenant_id == tenant_id),
                    )
                    .order_by(PermissionGrant.id)
                )
                for kind, statement in [
                    ("bindings", bindings),
                    ("versions", versions),
                    ("files", files),
                    ("menus", menus),
                    ("grant_sources", grant_sources),
                    ("workflow_grants", workflow_grants),
                ]:
                    rows = (await session.exec(statement.offset(offset).limit(limit + 1))).all()
                    report["truncated"][kind] = len(rows) > limit
                    report["next_offsets"][kind] = offset + limit if len(rows) > limit else None
                    for row in rows[:limit]:
                        child, parent = row[:2]
                        if kind == "bindings":
                            home = row[2]
                            if child.role_id == 1:
                                continue
                            if home is None or home.status != "active":
                                issue = "UNKNOWN_HOME"
                            elif parent is None:
                                issue = "MISSING_DEFINITION"
                            elif child.tenant_id != home.tenant_id:
                                issue = "BINDING_OUTSIDE_HOME_CANDIDATE"
                            elif parent.role_type == "tenant" and parent.tenant_id != home.tenant_id:
                                issue = "LOCAL_DEFINITION_OUTSIDE_HOME_CANDIDATE"
                            else:
                                continue
                            report["findings"].append(
                                {
                                    "kind": kind,
                                    "user_id": child.user_id,
                                    "role_id": child.role_id,
                                    "binding_tenant_id": child.tenant_id,
                                    "home_candidate": home.tenant_id if home else None,
                                    "issue": issue,
                                }
                            )
                        elif parent is None or child.tenant_id != parent.tenant_id:
                            report["findings"].append(
                                {
                                    "kind": kind,
                                    "id": str(child.id),
                                    "tenant_id": child.tenant_id,
                                    "parent_tenant_id": parent.tenant_id if parent else None,
                                    "issue": "MISSING_PARENT" if parent is None else "OWNER_MISMATCH",
                                }
                            )
                report["sql_inventory"] = {}
                inventories = [
                    (
                        "references",
                        select(BusinessResourceReference)
                        .where(
                            or_(
                                BusinessResourceReference.tenant_id == tenant_id,
                                BusinessResourceReference.target_tenant_id == tenant_id,
                            )
                        )
                        .order_by(BusinessResourceReference.id),
                        (
                            "id",
                            "tenant_id",
                            "source_type",
                            "source_id",
                            "source_version",
                            "target_type",
                            "target_id",
                            "target_tenant_id",
                            "legacy_invalid_reason",
                        ),
                    ),
                    (
                        "grants",
                        select(PermissionGrant)
                        .where(PermissionGrant.tenant_id == tenant_id)
                        .order_by(PermissionGrant.id),
                        ("id", "tenant_id", "resource_type", "resource_id", "model_key", "state", "projection_state"),
                    ),
                    (
                        "system_model_settings",
                        select(TenantSystemModelConfig)
                        .where(TenantSystemModelConfig.tenant_id == tenant_id)
                        .order_by(TenantSystemModelConfig.id),
                        ("id", "tenant_id", "key"),
                    ),
                ]
                for kind, query, fields in inventories:
                    rows = (await session.exec(query.offset(offset).limit(limit + 1))).all()
                    report["truncated"][kind] = len(rows) > limit
                    report["next_offsets"][kind] = offset + limit if len(rows) > limit else None
                    items = []
                    for row in rows[:limit]:
                        item = {field: getattr(row, field) for field in fields}
                        item["state_verification"] = "DOMAIN_RESOLUTION_NOT_RUN"
                        if kind == "references":
                            item["scope_relation"] = (
                                "UNKNOWN_TARGET_OWNER"
                                if row.target_tenant_id is None
                                else (
                                    "SAME_TENANT"
                                    if row.tenant_id == row.target_tenant_id
                                    else "CROSS_SCOPE_REQUIRES_DOMAIN_PROOF"
                                )
                            )
                        items.append(item)
                    report["sql_inventory"][kind] = items
        report["sql_page_complete"] = not any(report["truncated"].values())
        report["historical_compatibility_verified"] = False
        report["requires_further_verification"] = [
            "authoritative_home_and_department_facts",
            "permission_and_model_reference_coverage",
            "external_FGA_and_storage",
            "old_queue_messages",
            "concurrent_changes_during_inventory",
        ]
        return report
