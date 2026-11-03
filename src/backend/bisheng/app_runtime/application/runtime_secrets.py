"""Current execution snapshot only. No arbitrary historical plaintext API."""

from dataclasses import dataclass, field

from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.repositories.runtime_secret_repository import RuntimeSecretRepository
from bisheng.app_runtime.domain.services.runtime_payload import unseal


@dataclass(frozen=True)
class RunningEnvironmentSnapshot:
    operation_id: str
    version_id: str
    route_epoch: int
    env: dict[str, str] | None = field(repr=False)


async def running_environment_snapshot(app_id, *, session):
    context = await RuntimeSecretRepository.running_context(session, app_id)
    if context is None:
        return None
    route, op = context
    try:
        env = unseal(op.payload["sealed_env"])
    except RuntimeConflict:
        env = None
    return RunningEnvironmentSnapshot(
        operation_id=op.id, version_id=op.version_id, route_epoch=route.route_epoch, env=env
    )


async def rebuild_current(app_id, *, request, actor):
    from bisheng.app_runtime.domain.services.secret_rebuild_service import AppSecretRebuildService

    return await AppSecretRebuildService().rebuild_current(app_id, request=request, actor=actor)


async def rebuild_status(app_id, *, session):
    return await RuntimeSecretRepository.latest_rebuild(session, app_id)
