"""Browser-facing upload admission and read-only local item status."""

from dataclasses import asdict, dataclass
from types import MappingProxyType

from bisheng.core.context.tenant import get_current_tenant_id, is_management_all_tenants, is_tenant_filter_bypassed
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.provider_v1_runtime import ProviderFeatureUnavailable, resolve_space_route
from bisheng.knowledge.domain.repositories.provider_operation_repository import (
    ProviderOperationRepository,
    RequestKeyConflict,
)
from bisheng.knowledge.domain.repositories.provider_upload_quota_repository import QuotaExceeded


@dataclass(frozen=True)
class UploadAdmission:
    port: object
    user_limit: int
    tenant_limit: int


def _upload_deployments():
    # WeKnora upload admits only when a signed-user HMAC secret and dual byte
    # budgets are available; the tenant API key alone is not a receipt principal.
    from bisheng.knowledge.application.provider_weknora_upload import resolve_weknora_upload

    return MappingProxyType({"weknora": resolve_weknora_upload})


_UPLOAD_DEPLOYMENTS = _upload_deployments()


async def _actor(service):
    tenant = get_current_tenant_id()
    user = service.login_user
    actor = await service._permission_actor()
    if (
        type(tenant) is not int
        or tenant <= 0
        or is_tenant_filter_bypassed()
        or is_management_all_tenants()
        or user.tenant_id != tenant
        or actor.current_tenant_id != tenant
        or actor.subject_type != "user"
        or actor.subject_id != user.user_id
    ):
        raise ProviderFeatureUnavailable()
    return tenant, user.user_id


async def upload_admission(service, route):
    tenant, user = await _actor(service)
    if (
        route is None
        or route.tenant_id != tenant
        or type(route.capability_revision) is not int
        or route.capability_revision <= 0
    ):
        return None
    resolve = _UPLOAD_DEPLOYMENTS.get(route.provider_key)
    if resolve is None:
        return None
    admission = await resolve(route, user)
    if not isinstance(admission, UploadAdmission) or not all(
        type(limit) is int and 0 < limit < 2**63 for limit in (admission.user_limit, admission.tenant_limit)
    ):
        return None
    port = admission.port
    context = getattr(port, "context", None)
    if (
        not all(callable(getattr(port, name, None)) for name in ("validate_upload", "send", "lookup"))
        or getattr(context, "operation", None) != "upload"
        or getattr(port, "capability_revision", None) != route.capability_revision
        or any(
            getattr(context, key, None) != getattr(route, key)
            for key in (
                "tenant_id",
                "space_id",
                "provider_key",
                "generation",
                "instance_id",
                "remote_scope_id",
                "remote_kb_id",
            )
        )
    ):
        return None
    return admission


async def create_upload(service, space_id, request_key, *, parent_id, file_name, byte_count, sha256, stream):
    tenant, _ = await _actor(service)
    space = await service.require_upload_container(space_id, parent_id)
    if space.tenant_id != tenant:
        raise ProviderFeatureUnavailable()
    admission = await upload_admission(service, await resolve_space_route(space_id))
    if admission is None:
        raise ProviderFeatureUnavailable()
    try:
        item = await service.upload_application_factory().acreate_provider_file(
            knowledge=space,
            parent_id=parent_id,
            request_key=request_key,
            file_name=file_name,
            byte_count=byte_count,
            checksum=sha256,
            chunks=stream(),
            port=admission.port,
            user_limit=admission.user_limit,
            tenant_limit=admission.tenant_limit,
        )
    except (RequestKeyConflict, QuotaExceeded) as exc:
        raise ProviderFeatureUnavailable() from exc
    return asdict(item)


async def read_upload(service, space_id, request_key, *, parent_id=None):
    tenant, user = await _actor(service)
    async with get_async_db_session() as session:
        row = await ProviderOperationRepository().read_owned_upload(
            session, tenant_id=tenant, actor_id=user, space_id=space_id, request_key=request_key
        )
    if row is not None:
        # The caller must not substitute an authorized folder for the original one.
        manifest = row.target_manifest
        if not isinstance(manifest, list) or len(manifest) != 1 or not isinstance(manifest[0], dict):
            raise ProviderFeatureUnavailable()
        facts = manifest[0]
        if "parent_id" not in facts or not all(
            type(facts.get(k)) is int and facts[k] > 0 for k in ("file_id", "version_id")
        ):
            raise ProviderFeatureUnavailable()
        parent_id = facts["parent_id"]
        if parent_id is not None and (type(parent_id) is not int or parent_id <= 0):
            raise ProviderFeatureUnavailable()
    space = await service.require_upload_container(space_id, parent_id)
    if space.tenant_id != tenant or await _actor(service) != (tenant, user):
        raise ProviderFeatureUnavailable()
    if row is None:
        return {"state": "not_found", "operation_id": None, "file_id": None, "version_id": None}
    state = {
        "succeeded": "accepted",
        "failed": "reupload_required" if row.last_error_code == "not_received" else "conflict",
        "manual_review": "conflict",
    }.get(row.state, "unknown")
    return {
        "state": state,
        "operation_id": row.operation_id,
        "file_id": facts["file_id"],
        "version_id": facts["version_id"],
    }
