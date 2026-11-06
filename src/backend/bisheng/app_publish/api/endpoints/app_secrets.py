"""Platform-session environment settings; raw validation inputs never escape."""

from fastapi import APIRouter, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from bisheng.app_publish.domain.schemas.app_secrets import SecretDeleteInput, SecretRebuildInput, SecretSaveInput
from bisheng.app_publish.domain.services.app_secret_service import AppSecretService
from bisheng.app_runtime.application.runtime_secrets import rebuild_current
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.app_publish import AppSecretInvalidError
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200


class SecretRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                # Do not expose input, ctx, raw body, or dynamic error text.
                errors = [
                    {
                        "field": ".".join(
                            str(part)
                            for part in error["loc"][:3]
                            if part
                            in {
                                "body",
                                "value",
                                "expected_revision",
                                "request_id",
                                "expected_version_id",
                                "expected_config_revision",
                                "expected_route_epoch",
                                "confirm_restart",
                                "confirm_online_impact",
                            }
                        ),
                        "reason": error["type"],
                    }
                    for error in exc.errors()
                ]
                raise AppSecretInvalidError(errors=errors) from None

        return safe_handler


router = APIRouter(prefix="/apps", tags=["HostedAppEnvironment"], route_class=SecretRoute)


def service():
    return AppSecretService()


@router.get("/{app_id}/secrets", response_model=UnifiedResponseModel[dict])
async def get_secrets(app_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(data=await service().get(app_id, actor=user))


@router.put("/{app_id}/secrets/{name}", response_model=UnifiedResponseModel[dict])
async def save_secret(
    app_id: str, name: str, body: SecretSaveInput, user: UserPayload = Depends(UserPayload.get_login_user)
):
    return resp_200(
        data=await service().save(
            app_id, name, value=body.value.get_secret_value(), expected_revision=body.expected_revision, actor=user
        )
    )


@router.delete("/{app_id}/secrets/{name}", response_model=UnifiedResponseModel[dict])
async def delete_secret(
    app_id: str, name: str, body: SecretDeleteInput, user: UserPayload = Depends(UserPayload.get_login_user)
):
    return resp_200(
        data=await service().delete(
            app_id,
            name,
            expected_revision=body.expected_revision,
            confirm_online_impact=body.confirm_online_impact,
            actor=user,
        )
    )


@router.post("/{app_id}/secrets/rebuild", response_model=UnifiedResponseModel[dict])
async def rebuild(app_id: str, body: SecretRebuildInput, user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(data=await rebuild_current(app_id, request=body, actor=user))
