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
            seeded_preset_tool_types = False
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

                # Initialize the three hosted-app resource tiers (F055 AC-44).
                # Runs in its own session on purpose — it is a startup step, not
                # part of this unit of work — and is idempotent by ``code``, so
                # an upgrade never resets a tier a super admin retuned.
                await _init_resource_tiers()

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
                    seeded_preset_tool_types = True
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

                await _ensure_image_view_tool(session)
                await _ensure_web_fetch_tool(session)

            # Initialize Databaseconfig while init bypass is still active.
            await settings.init_config()

            # init dashboard data — dashboard is tenant-scoped since F048
            await init_dashboard_datasets()

            _bypass_tenant_filter.reset(_bypass_token)
            if settings.openfga.enabled:
                if seeded_preset_tool_types:
                    from bisheng.api.services.f048_system_resource_bootstrap import (
                        reconcile_fresh_install_system_resources,
                    )

                    report = await reconcile_fresh_install_system_resources()
                    logger.info(
                        "Seeded F048 system-owned resource projections: current={} missing_before={}",
                        report.current_count,
                        report.missing_count,
                    )
                from bisheng.api.services.f048_preset_dashboard_bootstrap import (
                    reconcile_preset_dashboard_permissions,
                )

                dashboard_report = await reconcile_preset_dashboard_permissions()
                logger.info(
                    "Reconciled preset dashboard owner projections: owner_ready={} current={} missing_before={}",
                    dashboard_report.owner_ready,
                    dashboard_report.current_count,
                    dashboard_report.missing_count,
                )

            await _sync_web_fetch_tool()

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

    root_dept_id = "BS@root"
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
                dept_id=root_dept_id,
                name="默认组织",
                parent_id=None,
                tenant_id=DEFAULT_TENANT_ID,
                path="",
                source="local",
                external_id=root_dept_id,
                status="active",
            )
            session.add(root_dept)
            await session.flush()
            await session.refresh(root_dept)
            root_dept.path = f"/{root_dept.id}/"
            tenant.root_dept_id = root_dept.id
            session.add(root_dept)
            await session.commit()
        elif root_dept.external_id != root_dept_id:
            # DM8 treats repeated NULL values as duplicates for this composite
            # unique key. Persist the internal identity before inserting guest.
            root_dept.external_id = root_dept_id
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
                external_id=guest_dept_id,
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
            if guest.external_id != guest_dept_id:
                guest.external_id = guest_dept_id
                changed = True
            expected_path_prefix = root_dept.path or ""
            if not (guest.path or "").startswith(expected_path_prefix):
                guest.path = f"{expected_path_prefix}{guest.id}/"
                changed = True
            if changed:
                session.add(guest)
                await session.commit()

    logger.info(f"Default root department ready (id={root_dept.id}), guest dept ready (dept_id={guest_dept_id})")


# Preset approval scenarios now live with the approval module
# (``approval/domain/services/approval_seed_service.py``): the same list has to
# be seeded both at boot (here) and whenever a tenant is created, and a second
# copy of it is how "the new tenant has no publish scenario" bugs get born.


async def _init_resource_tiers():
    """Idempotently seed the three hosted-app resource tiers (F055 AC-44).

    Delegates to ``ResourceTierService`` rather than writing rows here: the
    unit conversion between F054's vCPU floats and the table's integer
    millicores, and the "deployment configuration overrides the constant"
    precedence, both have exactly one implementation (F055 design D11).

    Imported lazily inside the function — ``common/`` must not carry a
    top-level import of a domain module (arch-guard RULE-1), and a boot step
    that only some deployments need has no business widening this module's
    import graph.

    Best-effort: a deployment whose tier table cannot be seeded must still
    finish booting. The publish pipeline fails loudly with 16223 on the first
    ``deploy`` instead, which is a far more locatable symptom than a backend
    that refuses to start.
    """
    try:
        from bisheng.app_publish.domain.services.resource_tier_service import ResourceTierService

        await ResourceTierService.seed_resource_tiers()
    except Exception as exc:
        # Best effort by design: see the docstring — the publish pipeline fails
        # loudly with 16223 on the first deploy, which is far easier to locate
        # than a backend that refuses to start.
        logger.warning(f"resource tier seed skipped: {exc}")


async def _init_default_approval_scenarios(session, tenant_id: int | None = None):
    """Idempotently seed the preset approval scenarios for one tenant.

    Boot calls it without a tenant and gets the default one, which is the
    historical behaviour. The tenant-scoped entry point used by both
    tenant-creation paths is
    ``approval_seed_service.seed_approval_scenarios_for_tenant``.

    Imported lazily: ``common/`` must not carry a top-level import of a domain
    module (arch-guard RULE-1), and the seed data belongs with the module that
    owns the scenarios.
    """
    from bisheng.approval.domain.services.approval_seed_service import seed_approval_scenarios_in_session
    from bisheng.core.context.tenant import DEFAULT_TENANT_ID

    await seed_approval_scenarios_in_session(session, DEFAULT_TENANT_ID if tenant_id is None else tenant_id)


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
        added_user_ids.append(int(uid))
    if added_user_ids:
        from bisheng.department.domain.services.department_service import (
            DepartmentMembershipProjectionService,
        )

        for uid in added_user_ids:
            await DepartmentMembershipProjectionService.aadd_member(
                user_id=uid,
                department_id=int(guest.id),
                is_primary=1,
                source="local",
            )


async def _ensure_image_view_tool(session) -> None:
    """Insert the Image View builtin tool when an existing database was seeded earlier."""
    from bisheng.core.context.tenant import DEFAULT_TENANT_ID

    existing = (
        await session.exec(
            select(GptsTools).where(
                GptsTools.tool_key == "image_view",
                GptsTools.tenant_id == DEFAULT_TENANT_ID,
                GptsTools.is_delete == 0,
            )
        )
    ).first()
    if existing is not None:
        return
    tool_type = GptsToolsType(
        name="Image View",
        logo="",
        description="使用模型管理中的视觉模型查看文档图片",
        server_host="",
        auth_method=0,
        api_key="",
        auth_type="basic",
        is_preset=1,
        user_id=None,
        is_delete=0,
        extra=json.dumps({"model_id": ""}),
        tenant_id=DEFAULT_TENANT_ID,
    )
    session.add(tool_type)
    await session.flush()
    session.add(
        GptsTools(
            name="Image View",
            logo=None,
            desc="查看文档中的图片，并判断哪些图片符合问题",
            tool_key="image_view",
            type=tool_type.id,
            extra="{}",
            is_preset=1,
            is_delete=0,
            user_id=None,
            api_params=[],
            tenant_id=DEFAULT_TENANT_ID,
        )
    )
    await session.commit()


WEB_FETCH_TOOL_KEY = "web_fetch"


def _load_web_fetch_seed() -> tuple[dict, dict]:
    """Return the (tool type, tool) seed rows of the web fetch tool.

    The seed JSON is the single source of the tool's name, description,
    parameters and default config (F085 design pitfall 9).
    """
    tools = json.loads(read_from_conf("../database/data/t_gpts_tools.json"))
    tool = next(item for item in tools if item.get("tool_key") == WEB_FETCH_TOOL_KEY)
    tool_types = json.loads(read_from_conf("../database/data/t_gpts_tools_type.json"))
    tool_type = next(item for item in tool_types if item.get("id") == tool["type"])
    return tool_type, tool


async def _ensure_web_fetch_tool(session) -> bool:
    """Insert the web fetch built-in tool into a database seeded before F085.

    Returns True when this call inserted the rows.
    """
    from bisheng.core.context.tenant import DEFAULT_TENANT_ID

    existing = (
        await session.exec(
            select(GptsTools).where(
                GptsTools.tool_key == WEB_FETCH_TOOL_KEY,
                GptsTools.tenant_id == DEFAULT_TENANT_ID,
                GptsTools.is_delete == 0,
            )
        )
    ).first()
    if existing is not None:
        return False
    type_seed, tool_seed = _load_web_fetch_seed()
    tool_type = GptsToolsType(
        **{key: value for key, value in type_seed.items() if key != "id"},
        tenant_id=DEFAULT_TENANT_ID,
    )
    session.add(tool_type)
    await session.flush()
    session.add(
        GptsTools(
            **{key: value for key, value in tool_seed.items() if key not in ("id", "type")},
            type=tool_type.id,
            tenant_id=DEFAULT_TENANT_ID,
        )
    )
    await session.commit()
    logger.info("Inserted the web fetch built-in tool: type_id={}", tool_type.id)
    return True


async def _project_root_web_fetch_tool() -> None:
    """Project the root tenant's web fetch tool type as a system-owned resource.

    Uses the fresh-install inventory spec; only a missing projection is written.
    """
    from bisheng.api.services.f048_system_resource_bootstrap import load_system_owned_resource_inventory
    from bisheng.core.context.tenant import DEFAULT_TENANT_ID, bypass_tenant_filter
    from bisheng.permission.application.access import get_f048_runtime
    from bisheng.permission.application.system_resource_reconcile import (
        SYSTEM_RESOURCE_BOOTSTRAP_OPERATOR_ID,
        reconcile_system_owned_resources,
    )

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            tool = (
                await session.exec(
                    select(GptsTools).where(
                        GptsTools.tool_key == WEB_FETCH_TOOL_KEY,
                        GptsTools.tenant_id == DEFAULT_TENANT_ID,
                        GptsTools.is_delete == 0,
                    )
                )
            ).first()
    if tool is None:
        return
    inventory = await load_system_owned_resource_inventory()
    specs = tuple(
        spec
        for spec in inventory.resources
        if spec.tenant_id == DEFAULT_TENANT_ID and spec.resource_id == str(tool.type)
    )
    if not specs:
        return
    await reconcile_system_owned_resources(
        await get_f048_runtime(),
        specs,
        apply=True,
        operator_id=SYSTEM_RESOURCE_BOOTSTRAP_OPERATOR_ID,
    )


async def _tenants_missing_web_fetch_tool() -> list[int]:
    """Active child tenants that have no web fetch tool row yet."""
    from bisheng.core.context.tenant import DEFAULT_TENANT_ID, bypass_tenant_filter
    from bisheng.database.models.tenant import Tenant

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            tenant_ids = (
                await session.exec(select(Tenant.id).where(Tenant.id != DEFAULT_TENANT_ID, Tenant.status == "active"))
            ).all()
            covered = set(
                (
                    await session.exec(
                        select(GptsTools.tenant_id).where(
                            GptsTools.tool_key == WEB_FETCH_TOOL_KEY,
                            GptsTools.is_delete == 0,
                        )
                    )
                ).all()
            )
    return [tenant_id for tenant_id in tenant_ids if tenant_id not in covered]


async def _sync_web_fetch_tool() -> None:
    """Make the web fetch tool usable everywhere after an upgrade (F085).

    Runs on every startup and only fills gaps, so a failed attempt heals on the
    next start. A failure is logged and never stops the startup.
    """
    if settings.openfga.enabled:
        try:
            await _project_root_web_fetch_tool()
        except Exception:
            logger.exception("Failed to project the root web fetch tool; non-admin users cannot use it yet")
    if not getattr(getattr(settings, "multi_tenant", None), "enabled", False):
        return
    try:
        tenant_ids = await _tenants_missing_web_fetch_tool()
    except Exception:
        logger.exception("Failed to list tenants missing the web fetch tool")
        return
    from bisheng.workstation.domain.services import WorkStationService

    for tenant_id in tenant_ids:
        try:
            await WorkStationService.acopy_root_builtin_tools_to_tenant(tenant_id)
        except Exception:
            logger.exception("Failed to copy the web fetch tool to tenant {}", tenant_id)


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
