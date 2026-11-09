"""Authenticated project orchestration; all SQL stays in repositories."""

import asyncio

from bisheng.chat_session.domain.repositories.project_repository import ProjectRepository
from bisheng.chat_session.domain.schemas.projects import ProjectActor
from bisheng.chat_session.domain.services.project_events import publish_project_change
from bisheng.common.schemas.api import PageData
from bisheng.core.context.tenant import tenant_execution_scope


class ProjectConversationPage(PageData[dict]):
    revision: str
    next_cursor: str | None


class ChatProjectService:
    @staticmethod
    def actor(user) -> ProjectActor:
        return ProjectActor(tenant_id=user.tenant_id, user_id=user.user_id)

    @staticmethod
    async def snapshot(actor, cursor=None):
        return await asyncio.to_thread(ProjectRepository.snapshot, actor, cursor=cursor)

    @staticmethod
    async def conversations(actor, **kwargs):
        result = await asyncio.to_thread(ProjectRepository.conversations, actor, **kwargs)
        return ProjectConversationPage(**result).model_dump(mode="json")

    @staticmethod
    async def version(actor):
        return await asyncio.to_thread(ProjectRepository.version, actor)

    @staticmethod
    async def execute(actor, action):
        result = await asyncio.to_thread(ProjectRepository.execute, actor, action)
        reason = "membership" if action.operation == "assign" else "project"
        # A replay may repair a lost notification, but never reruns the write.
        notification = await publish_project_change(actor, result["revision"], reason)
        return {**result, "notification": notification}

    @staticmethod
    async def identity_active(actor, user):
        from bisheng.user.domain.models.user import UserDao

        if actor != ChatProjectService.actor(user):
            return False
        with tenant_execution_scope(actor.tenant_id):
            current = await UserDao.aget_user(actor.user_id)
        return current is not None and not current.delete and int(current.token_version or 0) == user.token_version
