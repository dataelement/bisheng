"""Authenticated management API; SDK and internal transports have separate routes."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.schemas.runtime_delivery import RestoreInput, RuntimeProfileDefinition
from bisheng.app_runtime.domain.services.runtime_management_service import RuntimeManagementService
from bisheng.app_runtime.domain.services.runtime_profile_service import RuntimeProfileService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.app_factory import AppDataInvalidError, AppManageForbiddenError, AppOwnerOnlyError
from bisheng.common.schemas.api import resp_200

router = APIRouter(tags=["Runtime delivery management"])


async def result(awaitable):
    try:
        return resp_200(data=await awaitable)
    except RuntimeConflict as exc:
        if str(exc) == "natural_owner_required":
            raise AppOwnerOnlyError() from exc
        if str(exc) == "platform_super_admin_required":
            raise AppManageForbiddenError(reason="platform_super_admin_required") from exc
        raise AppDataInvalidError(reason=str(exc)) from exc


@router.get("/runtime/profiles")
async def profiles(user: UserPayload = Depends(UserPayload.get_login_user)):
    return await result(RuntimeProfileService().list_public())


@router.get("/runtime/profiles/defaults")
async def profile_defaults(user: UserPayload = Depends(UserPayload.get_login_user)):
    return await result(RuntimeProfileService().list_defaults())


@router.post("/runtime/profiles")
async def import_profile(body: RuntimeProfileDefinition, user: UserPayload = Depends(UserPayload.get_login_user)):
    return await result(RuntimeProfileService().import_revision(body.model_dump(mode="json"), actor=user))


class DefaultInput(BaseModel):
    language: str
    profile_id: str
    expected_generation: int = Field(ge=0)


@router.put("/runtime/profiles/default")
async def default_profile(body: DefaultInput, user: UserPayload = Depends(UserPayload.get_login_user)):
    return await result(RuntimeProfileService().set_default(**body.model_dump(), actor=user))


@router.post("/apps/{app_id}/runtime/materials")
async def materials(
    app_id: str,
    request: Request,
    profile: str,
    platform: str,
    sha256: str,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    return await result(
        RuntimeManagementService().import_materials(
            request.stream(), app_id=app_id, profile_reference=profile, platform=platform, sha256=sha256, actor=user
        )
    )


@router.post("/runtime/materials/public")
async def public_materials(
    request: Request, profile: str, platform: str, sha256: str, user: UserPayload = Depends(UserPayload.get_login_user)
):
    return await result(
        RuntimeManagementService().import_materials(
            request.stream(),
            app_id="",
            profile_reference=profile,
            platform=platform,
            sha256=sha256,
            actor=user,
            public=True,
        )
    )


@router.get("/apps/{app_id}/runtime/state")
async def runtime_state(app_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    return await result(RuntimeManagementService().state(app_id, user))


@router.get("/apps/{app_id}/runtime/snapshots")
async def snapshots(app_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    return await result(RuntimeManagementService().snapshots(app_id, user))


@router.post("/apps/{app_id}/runtime/restore", status_code=202)
async def restore(app_id: str, body: RestoreInput, user: UserPayload = Depends(UserPayload.get_login_user)):
    return await result(RuntimeManagementService().restore(app_id, body, user))


@router.get("/apps/{app_id}/runtime/operations/{operation_id}")
async def operation(app_id: str, operation_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    return await result(RuntimeManagementService().operation(app_id, operation_id, user))


@router.post("/apps/{app_id}/runtime/operations/{operation_id}/cancel")
async def cancel(app_id: str, operation_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    return await result(RuntimeManagementService().cancel(app_id, operation_id, user))


@router.post("/apps/{app_id}/runtime/upgrade")
async def upgrade(app_id: str, body: dict, user: UserPayload = Depends(UserPayload.get_login_user)):
    from bisheng.app_runtime.domain.services.runtime_upgrade_service import RuntimeUpgradeService

    if body.get("app_id") != app_id:
        raise AppDataInvalidError(reason="upgrade_scope_mismatch")
    return await result(RuntimeUpgradeService().import_binding(body, user))


@router.post("/apps/{app_id}/runtime/upgrade/rebind")
async def upgrade_rebind(app_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    from bisheng.app_runtime.domain.services.runtime_upgrade_service import RuntimeUpgradeService

    return await result(RuntimeUpgradeService().rebind(app_id, user))


@router.get("/runtime/profiles/{reference}/{os_name}/{architecture}")
async def frozen_profile(
    reference: str,
    os_name: str,
    architecture: str,
    language: str,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    return await result(RuntimeProfileService().resolve(language, reference, os_name + "/" + architecture))


class MaterialStateInput(BaseModel):
    enabled: bool


@router.patch("/apps/{app_id}/runtime/materials/{artifact_id}")
async def material_state(
    app_id: str, artifact_id: str, body: MaterialStateInput, user: UserPayload = Depends(UserPayload.get_login_user)
):
    return await result(RuntimeManagementService().set_material_enabled(app_id, artifact_id, body.enabled, user))
