"""Natural-person submission adapter; no service credential is issued."""

from dataclasses import dataclass

from bisheng.app_publish.domain.services.publish_pipeline_service import PublishPipelineService
from bisheng.common.errcode.app_factory import AppStateConflictError
from bisheng.common.errcode.app_publish import AppNotOwnedBySubjectError
from bisheng.dsh.domain.services.access import principal_scope


@dataclass(frozen=True)
class DesktopPublishIdentity:
    tenant_id: int
    resource_owner_user_id: int
    effective_user_id: int
    actor_id: int
    actor_name: str
    actor_kind: str = "natural_person"
    credential_id: None = None
    source: str = "desktop"


def publish_identity(actor, owner_user_id):
    return DesktopPublishIdentity(actor.tenant_id, owner_user_id, actor.user_id, actor.user_id, actor.user_name)


class DesktopPublishService:
    def __init__(self, apps):
        self.apps = apps

    async def accept(
        self,
        principal,
        package_path,
        *,
        app_id=None,
        base_version_id=None,
        confirm_schema_change=False,
        release_notes=None,
    ):
        with principal_scope(principal):
            if app_id:
                actor, app = await self.apps.require(principal, app_id, "edit", "publish")
                owner = int(app.owner_user_id)
                if app.current_version_id != base_version_id:
                    raise AppStateConflictError(
                        msg="The published version changed. Fetch source again and merge your changes.",
                        details={"reason": "base_version_changed"},
                    )
            else:
                actor = await self.apps.actor(principal)
                owner = actor.user_id
                if base_version_id is not None:
                    raise AppNotOwnedBySubjectError(details={"reason": "unexpected_base_version"})
            return await PublishPipelineService.accept(
                package_path=package_path,
                principal=publish_identity(actor, owner),
                app_id=app_id,
                confirm_schema_change=confirm_schema_change,
                release_notes=release_notes,
                base_version_id=base_version_id,
                check_base_version=bool(app_id),
            )

    async def status(self, principal, app_id, deployment_id):
        with principal_scope(principal):
            actor, app = await self.apps.require(principal, app_id, "edit")
            result = await PublishPipelineService.get_deployment_status(
                deployment_id, principal=publish_identity(actor, int(app.owner_user_id))
            )
            if result.get("app_id") != app_id:
                raise AppNotOwnedBySubjectError()
            return result
