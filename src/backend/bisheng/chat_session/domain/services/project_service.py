"""Authenticated project orchestration; all SQL stays in repositories."""

import asyncio

from bisheng.chat_session.domain.repositories.project_repository import ProjectRepository
from bisheng.chat_session.domain.schemas.projects import ProjectActor
from bisheng.common.schemas.api import PageData


class ProjectConversationPage(PageData[dict]):
    next_cursor: str | None


class ChatProjectService:
    @staticmethod
    def actor(user) -> ProjectActor:
        return ProjectActor(tenant_id=user.tenant_id, user_id=user.user_id)

    @staticmethod
    async def snapshot(actor):
        return await asyncio.to_thread(ProjectRepository.snapshot, actor)

    @staticmethod
    async def conversations(actor, **kwargs):
        result = await asyncio.to_thread(ProjectRepository.conversations, actor, **kwargs)
        return ProjectConversationPage(**result).model_dump(mode="json")

    @staticmethod
    async def execute(actor, action):
        return await asyncio.to_thread(ProjectRepository.execute, actor, action)
