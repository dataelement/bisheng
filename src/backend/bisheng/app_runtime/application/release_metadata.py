"""Release metadata updates require a persistent deployment and matching application."""

from bisheng.app_runtime.domain.services.app_meta_service import AppMetaService


async def update_meta_for_release(deployment_id: str, *, app_id: str, name=None, description=None, logo=None):
    return await AppMetaService.update_meta_for_release(
        deployment_id,
        app_id=app_id,
        name=name,
        description=description,
        logo=logo,
    )
