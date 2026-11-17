"""Business qualification and legacy membership cleanup for voluntary space exit."""

from typing import TYPE_CHECKING

from bisheng.common.errcode.knowledge_space import (
    SpaceGrantedNotJoinedError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.common.models.space_channel_member import SpaceChannelMemberDao, UserRoleEnum
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceExitStatus
from bisheng.permission.application import access

if TYPE_CHECKING:
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


class KnowledgeSpaceExitService:
    def __init__(self, owner: "KnowledgeSpaceService"):
        self.owner = owner

    async def _load(self, space_id: int):
        space = await KnowledgeDao.aquery_by_id(space_id)
        actor = await self.owner._permission_actor()
        if space is None or space.type != KnowledgeTypeEnum.SPACE.value or space.tenant_id != actor.current_tenant_id:
            raise SpaceNotFoundError()
        member = await SpaceChannelMemberDao.async_find_member(space_id, actor.user_id)
        creator = space.user_id == actor.user_id or (member and member.user_role == UserRoleEnum.CREATOR)
        return actor, member, bool(creator)

    async def _permission_context(self, space_id, actor):
        target = await self.owner.resolve_permission_target(resource_id=str(space_id), actor=actor, action="visible")
        directory = await access.get_grant_subject_directory()
        subjects = await directory.actor_projected_subjects(actor)
        runtime = await access.get_f048_runtime()
        return runtime, target, subjects

    async def status(self, space_id: int) -> KnowledgeSpaceExitStatus:
        actor, _, creator = await self._load(space_id)
        if creator:
            return KnowledgeSpaceExitStatus(can_exit=False, reason="creator")
        await self.owner._require_action("knowledge_space", space_id, "visible")
        runtime, target, subjects = await self._permission_context(space_id, actor)
        result = await runtime.personal_space_exit_status(actor=actor, target=target, actor_projected_subjects=subjects)
        return KnowledgeSpaceExitStatus(can_exit=result.can_exit, reason=result.reason)

    async def execute(self, space_id: int) -> bool:
        actor, member, creator = await self._load(space_id)
        if creator:
            raise SpacePermissionDeniedError()
        runtime, target, subjects = await self._permission_context(space_id, actor)
        result = await runtime.personal_space_exit_status(actor=actor, target=target, actor_projected_subjects=subjects)
        if result.reason == "creator":
            raise SpacePermissionDeniedError()
        if result.reason == "organization_grant":
            raise SpaceGrantedNotJoinedError()
        if result.can_exit:
            await self.owner._require_action("knowledge_space", space_id, "visible")
        try:
            await runtime.exit_personal_space(
                actor=actor,
                target=target,
                actor_projected_subjects=subjects,
                idempotency_key=f"space-exit:{space_id}:{actor.user_id}:{target.resource_version}",
            )
        except PermissionDeniedError as exc:
            raise SpaceGrantedNotJoinedError() from exc
        # Permission projection must succeed before deleting UI membership facts.
        # A lost-response retry may have no remaining grants and is a safe no-op.
        if member is not None:
            await SpaceChannelMemberDao.delete_space_member(space_id, actor.user_id)
        return True
