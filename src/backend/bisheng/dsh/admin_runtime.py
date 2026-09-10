"""Production administrative dependencies, shared with durable workers."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from bisheng.core.context.tenant import get_admin_scope_tenant_id, get_current_tenant_id
from bisheng.dsh.domain.repositories.admin_operation import DshOperationRepository
from bisheng.dsh.domain.repositories.policy import DshPolicyRepository
from bisheng.dsh.domain.services.admin import DshManagementService
from bisheng.dsh.domain.services.admin_policy import DshAdminService
from bisheng.dsh.domain.services.profile import profile_scope


@contextmanager
def operation_repository_scope():
    from bisheng.core.database import get_sync_db_session

    with get_sync_db_session() as session:
        yield DshOperationRepository(session)
        session.commit()


@contextmanager
def policy_repository_scope():
    from bisheng.core.database import get_sync_db_session

    with get_sync_db_session() as session:
        yield DshPolicyRepository(session)
        session.commit()


async def authorize_admin(actor_id: int, tenant_id: int | None, user_id: int | None = None):
    from bisheng.database.constants import AdminRole
    from bisheng.database.models.tenant import UserTenantDao
    from bisheng.permission.application import (
        PermissionObject,
        PermissionSubject,
        get_permission_relation_api,
        is_tenant_admin,
    )
    from bisheng.user.domain.models.user import UserDao
    from bisheng.user.domain.models.user_role import UserRoleDao

    actor_user = await UserDao.aget_user(actor_id)
    if actor_user is None or actor_user.delete != 0:
        raise HTTPException(403, "Administrator unavailable")
    permissions = await get_permission_relation_api()
    is_super = await permissions.check(
        subject=PermissionSubject("user", str(actor_id)),
        relation="super_admin",
        resource=PermissionObject("system", "global"),
    )
    if not is_super:
        is_super = any(row.role_id == AdminRole for row in await UserRoleDao.aget_user_roles(actor_id))
    scope = get_current_tenant_id()
    # A deliberate Child administrative scope remains restricted even for Root.
    instance = is_super and get_admin_scope_tenant_id() is None
    if not instance and (scope is None or (tenant_id is not None and tenant_id != scope)):
        raise HTTPException(403, "Target tenant is outside administrative scope")
    if not is_super and not await is_tenant_admin(actor_id, scope):
        raise HTTPException(403, "Tenant administrator required")
    target = tenant_id if tenant_id is not None else (None if instance else scope)
    if user_id is not None and target is None:
        membership = await UserTenantDao.aget_active_user_tenant(user_id)
        if membership is None:
            raise HTTPException(403, "Target user has no active tenant")
        target = membership.tenant_id
    actor_membership = await UserTenantDao.aget_active_user_tenant(actor_id)
    if actor_membership is None:
        raise HTTPException(403, "Administrator has no active tenant")
    return {
        "user_id": str(actor_id),
        "tenant_id": str(scope or actor_membership.tenant_id),
        "scope": "instance" if instance else "tenant",
    }, target


@dataclass
class AdminRuntime:
    admin: DshManagementService
    policy: DshAdminService
    profiles: object
    repository_scope: object = operation_repository_scope


async def get_admin_runtime(runtime, *, quota=None, usage=None):
    if getattr(runtime, "administration", None) is not None:
        return runtime.administration
    from bisheng.dsh.runtime import get_model_runtime, read_policy
    from bisheng.llm.domain.services.llm import LLMService
    from bisheng.user.domain.services.dsh_display import read_dsh_display_profiles
    from bisheng.worker.dsh.profiles import ProfileOutboxWorker

    model_runtime = None
    if quota is None:
        model_runtime = await get_model_runtime(runtime)
        quota, usage = model_runtime.quota, model_runtime.usage

    def now():
        return datetime.now(UTC).replace(tzinfo=None)

    async def validate_target(actor_id, user_id):
        tenant = get_current_tenant_id()
        await authorize_admin(actor_id, tenant, user_id)
        record = await runtime_identity(tenant, user_id)
        return bool(record and record.active and record.tenant_active)

    async def validate_models(actor_id, user_id, model_ids):
        if not await validate_target(actor_id, user_id):
            return False
        for model_id in model_ids:
            await LLMService.get_dsh_model_snapshot(model_id)
        return True

    async def live_reader(user_id, month):
        if model_runtime is not None:
            from types import SimpleNamespace

            return await model_runtime.prepare_month(
                SimpleNamespace(tenant_id=get_current_tenant_id(), user_id=user_id), month
            )
        return await usage.read_usage(get_current_tenant_id(), user_id, month)

    from bisheng.dsh.runtime import read_persisted_usage

    async def available_models_reader(_user_id):
        return await read_available_models(await LLMService.get_dsh_model_ids(), LLMService.get_dsh_model_snapshot)

    policy_view = build_policy_view(
        policy_reader=read_policy,
        live_reader=live_reader,
        persisted_reader=read_persisted_usage,
        billing_timezone=runtime.settings.billing_timezone,
        unknown_reader=read_unknown_pending,
        available_models_reader=available_models_reader,
        last_call_reader=read_last_call,
    )

    class ActivatedQuota:
        def __getattr__(self, name):
            async def invoke(*args, **kwargs):
                if model_runtime is not None:
                    await model_runtime.activate()
                return await getattr(quota, name)(*args, **kwargs)

            return invoke

    policy = DshAdminService(
        repository_scope=policy_repository_scope,
        quota=ActivatedQuota(),
        authorize=validate_target,
        validate_models=validate_models,
        now=now,
    )
    admin = DshManagementService(
        repository_scope=operation_repository_scope,
        gateway=runtime.gateway,
        authorize=authorize_admin,
        profiles=read_dsh_display_profiles,
        policy=policy,
        policy_view=policy_view,
        now=now,
        model_users_view=read_model_users,
        model_policy_view=read_model_policy,
    )
    result = AdminRuntime(
        admin,
        policy,
        ProfileOutboxWorker(repository_scope=operation_repository_scope, gateway=runtime.gateway, now=now),
    )
    runtime.administration = result
    return result


async def runtime_identity(tenant_id, user_id):
    from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords

    with profile_scope(tenant_id):
        return await CurrentIdentityRecords().get(str(tenant_id), str(user_id))


def build_policy_view(
    *,
    policy_reader,
    live_reader,
    persisted_reader,
    billing_timezone,
    unknown_reader=None,
    available_models_reader=None,
    last_call_reader=None,
):
    async def view(user_id):
        policy = await policy_reader(user_id)
        month = datetime.now(UTC).astimezone(ZoneInfo(billing_timezone)).strftime("%Y-%m")
        snapshot = None
        if policy is not None:
            try:
                snapshot = await live_reader(user_id, month)
            except Exception:
                try:
                    snapshot = await persisted_reader(user_id, month)
                except Exception:
                    snapshot = None
        limit = policy.monthly_token_limit if policy else 0
        model_limits = {str(item.model_id): item.monthly_token_limit for item in policy.model_configs} if policy else {}
        usage_view = {
            "month": month,
            "billing_timezone": billing_timezone,
            "used": None,
            "limit": limit,
            "remaining": None,
            "source": "unavailable",
            "as_of": None,
            "quota_state": "unavailable",
            "models": None,
            "model_limits": model_limits,
            "unknown_pending": None,
        }
        if snapshot:
            live = snapshot["source"] == "live"
            state = "unavailable"
            if live and snapshot["quota_state"] == "ready":
                state = "available" if snapshot["remaining"] > 0 else "exhausted"
            as_of = snapshot.get("as_of")
            if isinstance(as_of, datetime):
                as_of = (
                    (as_of.replace(tzinfo=UTC) if as_of.tzinfo is None else as_of).isoformat().replace("+00:00", "Z")
                )
            usage_view.update(
                used=snapshot["used"],
                limit=snapshot["limit"],
                remaining=snapshot["remaining"],
                source="live" if live else "persisted",
                as_of=as_of,
                quota_state=state,
                models=snapshot.get("models"),
                model_limits=snapshot.get("model_limits"),
                unknown_pending=snapshot.get("unknown_pending"),
            )
        if usage_view["unknown_pending"] is None and unknown_reader is not None:
            try:
                usage_view["unknown_pending"] = await unknown_reader(user_id)
            except Exception:
                pass
        from bisheng.dsh.domain.schemas.admin import AvailableModel, LastCallSnapshot

        candidates, candidate_source = [], "unavailable"
        if available_models_reader is not None:
            try:
                candidates = [
                    AvailableModel.model_validate(row).model_dump() for row in await available_models_reader(user_id)
                ]
                candidate_source = "live"
            except Exception:
                pass
        last_call, last_call_source = None, "unavailable"
        if last_call_reader is not None:
            try:
                latest = await last_call_reader(user_id)
                last_call = LastCallSnapshot.model_validate(latest).model_dump() if latest is not None else None
                last_call_source = "persisted"
            except Exception:
                pass
        data = (
            {"version": policy.version, "quota_sync_state": policy.quota_sync_state}
            if policy
            else {"version": 0, "quota_sync_state": "PENDING"}
        )
        data.pop("model_configs", None)
        return {
            **data,
            "tenant_id": get_current_tenant_id(),
            "available_models": candidates,
            "available_models_source": candidate_source,
            "last_call": last_call,
            "last_call_source": last_call_source,
            "models": [item.model_dump() for item in policy.model_configs] if policy else [],
            "usage": usage_view,
        }

    return view


async def read_unknown_pending(user_id):
    import asyncio

    from bisheng.core.database import get_sync_db_session
    from bisheng.dsh.domain.repositories.usage import DshUsageRepository

    def read():
        with get_sync_db_session() as session:
            return DshUsageRepository(session).unknown_pending(user_id)

    return await asyncio.to_thread(read)


async def read_available_models(model_ids, model_loader):
    from bisheng.common.errcode.dsh import DshModelNotAllowedError
    from bisheng.dsh.domain.repositories.admin_operation import require_tenant
    from bisheng.dsh.domain.schemas.admin import AvailableModel

    tenant_id = require_tenant()
    result = []
    for model_id in sorted({int(value) for value in model_ids}):
        try:
            model, server = await model_loader(model_id)
        except DshModelNotAllowedError:
            continue
        result.append(
            AvailableModel(
                id=model.id,
                name=f"{server.name.strip() or server.type} / {model.model_name.strip() or model.name}",
                is_root_shared=model.tenant_id == 1 and tenant_id != 1,
            ).model_dump()
        )
    return result


async def read_model_users(model_id, *, after_user_id=0, limit=20, keyword="", authorized_only=False):
    import asyncio

    from bisheng.common.errcode.dsh import DshModelNotAllowedError
    from bisheng.core.database import get_sync_db_session
    from bisheng.dsh.domain.repositories.model_access import DshModelAccessRepository
    from bisheng.llm.domain.services.llm import LLMService
    from bisheng.user.domain.services.dsh_access import list_dsh_access_users

    candidates = await read_available_models([model_id], LLMService.get_dsh_model_snapshot)
    if not candidates:
        raise DshModelNotAllowedError()
    ids = None
    if authorized_only:

        def read_ids():
            with get_sync_db_session() as session:
                return DshModelAccessRepository(session).authorized_user_ids(
                    model_id, after_user_id=after_user_id, limit=limit
                )

        ids = await asyncio.to_thread(read_ids)
    rows = await list_dsh_access_users(
        after_user_id=after_user_id, limit=limit, keyword=keyword, user_ids=ids[:limit] if ids is not None else None
    )

    def read():
        with get_sync_db_session() as session:
            return DshModelAccessRepository(session).users(rows, model_id=model_id, limit=limit)

    page = await asyncio.to_thread(read)
    if ids is not None:
        page.update(has_more=len(ids) > limit, next_cursor=str(ids[limit - 1]) if len(ids) > limit else None)
    return {"model": candidates[0], "tenant_id": get_current_tenant_id(), **page}


async def read_last_call(user_id):
    import asyncio

    from bisheng.core.database import get_sync_db_session
    from bisheng.dsh.domain.repositories.admin_queries import DshAdminQueryRepository

    def read():
        with get_sync_db_session() as session:
            return DshAdminQueryRepository(session).last_call(user_id)

    return await asyncio.to_thread(read)


async def read_model_policy(user_id, model_id):
    import asyncio

    from bisheng.core.database import get_sync_db_session

    def read():
        with get_sync_db_session() as session:
            row = DshPolicyRepository(session).get_model(user_id, model_id)
            return {
                "user_id": user_id,
                "model_id": model_id,
                "enabled": bool(row.enabled) if row else False,
                "monthly_token_limit": row.monthly_token_limit if row else 0,
                "version": row.version if row else 0,
                "pending_operation_id": row.pending_operation_id if row else None,
            }

    return await asyncio.to_thread(read)
