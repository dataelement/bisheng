"""Public F055 interface. Caller owns the formal snapshot transaction."""

from bisheng.app_publish.domain.services.app_secret_service import AppSecretService


async def formal_snapshot(app, approved_version, *, session, expected_revision=None):
    return await AppSecretService().formal_snapshot(
        app, approved_version, session=session, expected_revision=expected_revision
    )


def preview_environment(declaration):
    return AppSecretService.preview_environment(declaration)


async def delete_for_app(app_id):
    await AppSecretService().delete_for_app(app_id)


async def secret_reference_status(app_id, declaration):
    return await AppSecretService().reference_status(app_id, declaration)
