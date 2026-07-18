import hashlib
import json
import os

from loguru import logger
from sqlmodel import select, update

from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.database import get_async_db_session, get_database_connection
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.database.constants import AdminRole, DefaultRole
from bisheng.database.models.role import Role
from bisheng.database.models.role_access import AccessType, RoleAccess, WebMenuResource
from bisheng.database.models.template import Template
from bisheng.telemetry_search.domain.init_dataset import init_dashboard_datasets
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRoleDao


async def init_default_data():
    """Initialize Database"""
    redis_client = await get_redis_client()
    if await redis_client.asetNx("init_default_data", "1"):
        try:
            db_manager = await get_database_connection()
            await db_manager.create_db_and_tables()
            # Bypass tenant filter during init — no tenant context available at startup
            from bisheng.core.context.tenant import _bypass_tenant_filter

            _bypass_token = _bypass_tenant_filter.set(True)
            async with get_async_db_session() as session:
                db_role = await session.exec(select(Role).limit(1))
                db_role = db_role.all()
                if not db_role:
                    # Initialize system configuration, Admin has all permissions
                    db_role = Role(
                        id=AdminRole,
                        role_name="System Admin",
                        remark="System highest privileges",
                        group_id=None,
                        role_type="global",
                    )
                    session.add(db_role)
                    db_role_normal = Role(
                        id=DefaultRole, role_name="普通用户", remark="普通用户", group_id=None, role_type="global"
                    )
                    session.add(db_role_normal)
                    # Grant DefaultRole WEB_MENU permissions (F005: updated for v2.5)
                    session.add_all(
                        [
                            RoleAccess(
                                role_id=DefaultRole,
                                type=AccessType.WEB_MENU.value,
                                third_id=WebMenuResource.WORKSTATION.value,
                            ),
                            RoleAccess(
                                role_id=DefaultRole, type=AccessType.WEB_MENU.value, third_id=WebMenuResource.HOME.value
                            ),
                            RoleAccess(
                                role_id=DefaultRole,
                                type=AccessType.WEB_MENU.value,
                                third_id=WebMenuResource.LINSIGHT_TASK_MODE.value,
                            ),
                            RoleAccess(
                                role_id=DefaultRole, type=AccessType.WEB_MENU.value, third_id=WebMenuResource.APPS.value
                            ),
                            RoleAccess(
                                role_id=DefaultRole,
                                type=AccessType.WEB_MENU.value,
                                third_id=WebMenuResource.SUBSCRIPTION.value,
                            ),
                            RoleAccess(
                                role_id=DefaultRole,
                                type=AccessType.WEB_MENU.value,
                                third_id=WebMenuResource.BUILD.value,
                            ),
                            RoleAccess(
                                role_id=DefaultRole,
                                type=AccessType.WEB_MENU.value,
                                third_id=WebMenuResource.KNOWLEDGE.value,
                            ),
                            RoleAccess(
                                role_id=DefaultRole,
                                type=AccessType.WEB_MENU.value,
                                third_id=WebMenuResource.KNOWLEDGE_SPACE.value,
                            ),
                            RoleAccess(
                                role_id=DefaultRole,
                                type=AccessType.WEB_MENU.value,
                                third_id=WebMenuResource.MODEL.value,
                            ),
                        ]
                    )
                    await session.commit()
                # Initialize default tenant (F001)
                await _init_default_tenant(session)
                # Initialize default root department (F002)
                await _init_default_root_department(session)

                user = await session.exec(select(User).limit(1))
                user = user.all()
                if not user and settings.admin:
                    md5 = hashlib.md5()
                    md5.update(settings.admin.get("password").encode("utf-8"))
                    user = User(
                        user_id=1,
                        user_name=settings.admin.get("user_name"),
                        password=md5.hexdigest(),
                    )
                    session.add(user)
                    await session.commit()
                    await session.refresh(user)
                    await UserRoleDao.set_admin_user(user.user_id)
                    from bisheng.permission.domain.services.legacy_rbac_sync_service import (
                        LegacyRBACSyncService,
                    )

                    await LegacyRBACSyncService.sync_user_auth_created(
                        user.user_id,
                        [AdminRole],
                    )

                await _backfill_guest_department_membership(session)

                # Initialize preset approval scenarios (channel / knowledge-space subscribe)
                await _init_default_approval_scenarios(session)

                # Initialize preset application templates
                templates = await session.exec(select(Template).limit(1))
                templates = templates.all()
                if not templates:
                    json_items = json.loads(read_from_conf("../database/data/template.json"))
                    for item in json_items:
                        session.add(Template(**item))
                    await session.commit()

                # Initialize preset tools list
                preset_tools = await session.exec(select(GptsTools).limit(1))
                preset_tools = preset_tools.all()
                if not preset_tools:
                    preset_tools = []
                    json_items = json.loads(read_from_conf("../database/data/t_gpts_tools.json"))
                    for item in json_items:
                        preset_tool = GptsTools(**item)
                        preset_tools.append(preset_tool)
                    session.add_all(preset_tools)
                    await session.commit()
                # Initialize Preset Tool Categories
                preset_tools_type = await session.exec(select(GptsToolsType).limit(1))
                preset_tools_type = preset_tools_type.all()
                if not preset_tools_type:
                    preset_tools_type = []
                    json_items = json.loads(read_from_conf("../database/data/t_gpts_tools_type.json"))
                    for item in json_items:
                        preset_tool_type = GptsToolsType(**item)
                        preset_tools_type.append(preset_tool_type)
                    session.add_all(preset_tools_type)
                    await session.commit()
                    # Set the category the preset tool belongs to, needs to be consistent with the preset data, soidIs Fixed
                    for i in range(1, 7):
                        await session.exec(update(GptsTools).where(GptsTools.id == i).values(type=i))
                    # Tools under the category of Sky Eye Examination
                    tyc_types: list[int] = list(range(7, 18))
                    await session.exec(update(GptsTools).where(GptsTools.id.in_(tyc_types)).values(type=7))
                    # Instruments belonging to the financial category
                    jr_types: list[int] = list(range(18, 28))
                    await session.exec(update(GptsTools).where(GptsTools.id.in_(jr_types)).values(type=8))
                    await session.commit()

            _bypass_tenant_filter.reset(_bypass_token)

            # Initialize Databaseconfig
            await settings.init_config()

            # init dashboard data
            await init_dashboard_datasets()

        except Exception as exc:
            # if the exception involves tables already existing
            # we can ignore it
            if "already exists" not in str(exc):
                logger.exception(f"Error creating DB and tables: {exc}")
                raise RuntimeError("Error creating DB and tables") from exc
        finally:
            await redis_client.adelete("init_default_data")


def read_from_conf(file_path: str) -> str:
    # Get current path
    current_path = os.path.dirname(os.path.abspath(__file__))

    file_path = os.path.join(current_path, file_path)

    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    return content


async def _init_default_tenant(session):
    """Idempotently create the default tenant (id=1).

    Called during init_default_data() to keep startup lean: it only guarantees
    the default tenant row exists. Uses bypass_tenant_filter() since tenant
    filter events might be active.

    Backfilling ``user_tenant`` associations for pre-existing users is a one-off
    data task — it scans the whole ``users``/``user_tenant`` tables and must not
    run on every boot. It now lives in
    ``scripts/backfill_user_tenant_associations.py``. Runtime tenant scoping
    already falls back to ``DEFAULT_TENANT_ID`` for users without a row (see
    ``UserPayload`` tenant resolution), so a missing association never blocks
    login or queries — the backfill is pure data hygiene.
    """
    from bisheng.core.context.tenant import DEFAULT_TENANT_ID, bypass_tenant_filter
    from bisheng.database.models.tenant import Tenant

    with bypass_tenant_filter():
        existing = (await session.exec(select(Tenant).where(Tenant.id == DEFAULT_TENANT_ID))).first()
        if not existing:
            tenant = Tenant(
                id=DEFAULT_TENANT_ID,
                tenant_code="default",
                tenant_name="Default Tenant",
                status="active",
            )
            session.add(tenant)
            await session.commit()

    logger.info(f"Default tenant ready (id={DEFAULT_TENANT_ID})")


async def _init_default_root_department(session):
    """Idempotently create the default root department for the default tenant.

    Called during init_default_data() after _init_default_tenant().
    Uses bypass_tenant_filter() since tenant filter events might be active.

    Part of F002-department-tree.
    """
    from bisheng.core.context.tenant import DEFAULT_TENANT_ID, bypass_tenant_filter
    from bisheng.database.models.department import Department
    from bisheng.database.models.tenant import Tenant

    guest_dept_id = "BS@guest"
    guest_name = "临时访客"
    guest_sort_order = 2147483647

    with bypass_tenant_filter():
        # Check if default tenant exists and has no root_dept_id yet
        tenant = (await session.exec(select(Tenant).where(Tenant.id == DEFAULT_TENANT_ID))).first()
        if tenant is None:
            return

        root_dept = None
        if tenant.root_dept_id is not None:
            root_dept = (await session.exec(select(Department).where(Department.id == tenant.root_dept_id))).first()

        if root_dept is None:
            root_dept = Department(
                dept_id="BS@root",
                name="默认组织",
                parent_id=None,
                tenant_id=DEFAULT_TENANT_ID,
                path="",
                source="local",
                status="active",
            )
            session.add(root_dept)
            await session.flush()
            await session.refresh(root_dept)
            root_dept.path = f"/{root_dept.id}/"
            tenant.root_dept_id = root_dept.id
            session.add(root_dept)
            await session.commit()

        guest = (await session.exec(select(Department).where(Department.dept_id == guest_dept_id))).first()
        if guest is None:
            guest = Department(
                dept_id=guest_dept_id,
                name=guest_name,
                parent_id=root_dept.id,
                tenant_id=DEFAULT_TENANT_ID,
                path=f"{root_dept.path}",
                source="local",
                status="active",
                sort_order=guest_sort_order,
            )
            session.add(guest)
            await session.flush()
            await session.refresh(guest)
            guest.path = f"{root_dept.path}{guest.id}/"
            session.add(guest)
            await session.commit()
        else:
            changed = False
            if guest.parent_id != root_dept.id:
                guest.parent_id = root_dept.id
                changed = True
            if guest.sort_order != guest_sort_order:
                guest.sort_order = guest_sort_order
                changed = True
            expected_path_prefix = root_dept.path or ""
            if not (guest.path or "").startswith(expected_path_prefix):
                guest.path = f"{expected_path_prefix}{guest.id}/"
                changed = True
            if changed:
                session.add(guest)
                await session.commit()

    logger.info(f"Default root department ready (id={root_dept.id}), guest dept ready (dept_id={guest_dept_id})")


# Preset approval scenarios seeded on first deploy. Each scenario gets one
# catch-all "default branch" routed to a single-node "default flow"; the node is
# OR-mode (或签, any one approver passes) and resolves approvers from the
# resource's owner + manager roles.
_DEFAULT_APPROVAL_SCENARIO_SEEDS = [
    {
        "scenario_code": "channel_subscribe_request",
        "scenario_name": "频道订阅审批",
        "flow_code": "channel_subscribe_default_flow",
        "flow_name": "默认流程",
        "node_code": "channel_owner_manager",
        "node_name": "频道负责人审批",
        "sources": [{"type": "channel_owner"}, {"type": "channel_manager"}],
    },
    {
        "scenario_code": "knowledge_space_subscribe_request",
        "scenario_name": "知识空间加入审批",
        "flow_code": "knowledge_space_subscribe_default_flow",
        "flow_name": "默认流程",
        "node_code": "knowledge_space_owner_manager",
        "node_name": "知识空间负责人审批",
        "sources": [{"type": "knowledge_space_owner"}, {"type": "knowledge_space_manager"}],
    },
]


async def _init_default_approval_scenarios(session):
    """Idempotently seed preset approval scenarios for the default tenant.

    Mirrors what the admin UI builds when an operator configures a scenario:
    scenario → catch-all route (default branch) → flow definition → active flow
    version → single OR-mode node. Existing scenarios (matched by
    ``tenant_id + scenario_code``) are left untouched so re-running init or a
    later manual edit is never overwritten.
    """
    from bisheng.approval.domain.models.approval_scenario import (
        ApprovalFlowDefinition,
        ApprovalFlowVersion,
        ApprovalNodeDefinition,
        ApprovalRouteRule,
        ApprovalScenario,
    )
    from bisheng.core.context.tenant import DEFAULT_TENANT_ID, bypass_tenant_filter

    with bypass_tenant_filter():
        for seed in _DEFAULT_APPROVAL_SCENARIO_SEEDS:
            existing = (
                await session.exec(
                    select(ApprovalScenario).where(
                        ApprovalScenario.tenant_id == DEFAULT_TENANT_ID,
                        ApprovalScenario.scenario_code == seed["scenario_code"],
                    )
                )
            ).first()
            if existing:
                continue

            scenario = ApprovalScenario(
                tenant_id=DEFAULT_TENANT_ID,
                scenario_code=seed["scenario_code"],
                scenario_name=seed["scenario_name"],
                enabled=True,
            )
            session.add(scenario)
            await session.flush()
            await session.refresh(scenario)

            flow = ApprovalFlowDefinition(
                tenant_id=DEFAULT_TENANT_ID,
                scenario_id=scenario.id,
                flow_code=seed["flow_code"],
                flow_name=seed["flow_name"],
                is_active=True,
            )
            session.add(flow)
            await session.flush()
            await session.refresh(flow)

            node_snapshot = {
                "node_code": seed["node_code"],
                "node_name": seed["node_name"],
                "node_order": 1,
                "node_mode": "or",
                "approver_config": {"sources": seed["sources"]},
            }
            version = ApprovalFlowVersion(
                tenant_id=DEFAULT_TENANT_ID,
                flow_definition_id=flow.id,
                version_no=1,
                is_active=True,
                definition_snapshot={"nodes": [node_snapshot]},
            )
            session.add(version)
            await session.flush()
            await session.refresh(version)

            session.add(
                ApprovalNodeDefinition(
                    tenant_id=DEFAULT_TENANT_ID,
                    flow_version_id=version.id,
                    node_code=seed["node_code"],
                    node_name=seed["node_name"],
                    node_order=1,
                    node_mode="or",
                    approver_config={"sources": seed["sources"]},
                )
            )
            session.add(
                ApprovalRouteRule(
                    tenant_id=DEFAULT_TENANT_ID,
                    scenario_id=scenario.id,
                    route_name="默认分支",
                    route_type="flow",
                    sort_order=1,
                    flow_definition_id=flow.id,
                    match_config={},
                    enabled=True,
                )
            )
            await session.commit()
            logger.info(f"Seeded approval scenario {seed['scenario_code']} (id={scenario.id}) for default tenant")


async def _backfill_guest_department_membership(session):
    """Ensure users have at least one department; fallback to 临时访客."""
    from bisheng.database.models.department import Department, UserDepartment

    guest = (
        await session.exec(
            select(Department).where(
                Department.dept_id == "BS@guest",
                Department.status == "active",
            )
        )
    ).first()
    if not guest:
        return

    user_rows = (await session.exec(select(User.user_id))).all()
    if not user_rows:
        return

    alreday_insert = (await session.exec(select(UserDepartment.id))).first()
    if alreday_insert:
        logger.info("Already have user in department, guest dept ready, not handle every times")
        return

    added_user_ids = []
    for uid in user_rows:
        has_any = (await session.exec(select(UserDepartment.id).where(UserDepartment.user_id == uid))).first()
        if has_any is not None:
            continue
        session.add(
            UserDepartment(
                user_id=uid,
                department_id=guest.id,
                is_primary=1,
                source="local",
            )
        )
        added_user_ids.append(int(uid))
    await session.commit()
    if added_user_ids:
        from bisheng.department.domain.services.department_change_handler import (
            DepartmentChangeHandler,
        )

        ops = DepartmentChangeHandler.on_members_added(guest.id, added_user_ids)
        await DepartmentChangeHandler.execute_async(ops)


def upload_preset_minio_file():
    """Upload preset file tominio, To work with workflow templates"""
    minio_client = get_minio_storage_sync()
    # Upload it 「Multi-Assistant Parallelism+Serial Report Generation」 Required for workflow templatesdocxDoc.
    template_data = read_from_conf("../database/data/0254d1808a5247d2a3ee0d0011819acb.docx")
    minio_client.put_object_sync(
        bucket_name=minio_client.bucket,
        object_name="workflow/report/0254d1808a5247d2a3ee0d0011819acb.docx",
        file=template_data,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
