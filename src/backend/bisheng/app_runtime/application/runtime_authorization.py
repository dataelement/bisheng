"""Public frozen-origin contract, free of persistence models."""

from bisheng.app_runtime.domain.services.app_authorization_service import AppAuthorizationService
from bisheng.app_runtime.domain.services.runtime_authorization_service import RuntimeAuthorizationService


async def capture_user_authorization(identity, app_id, purpose, *, version_id="", resume=False):
    app = await AppAuthorizationService.load_app(app_id)
    return await RuntimeAuthorizationService.capture_user(identity, app, purpose, version_id=version_id, resume=resume)


async def validate_user_authorization(context, app_id, *, version_id):
    app = await AppAuthorizationService.load_app(app_id)
    if app is None:
        from bisheng.common.errcode.app_factory import AppNotFoundError

        raise AppNotFoundError()
    await RuntimeAuthorizationService.validate_user(context, app, version_id=version_id)
