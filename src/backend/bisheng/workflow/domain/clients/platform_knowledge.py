"""昆联知识库适配接口。"""

from typing import Protocol

from bisheng.common.errcode.flow import PlatformKnowledgeNotReadyError
from bisheng.core.config.settings import PlatformKnowledgeConf
from bisheng.workflow.domain.schemas.platform_knowledge import KnowledgeActor


class PlatformKnowledgeProvider(Protocol):
    async def list_knowledge(self, actor: KnowledgeActor, cursor: str | None, name: str | None) -> dict: ...
    async def get_knowledge(self, actor: KnowledgeActor, resource_id: str) -> dict: ...
    async def check_use(self, actor: KnowledgeActor, resource_id: str) -> None: ...
    async def retrieve(
        self, actor: KnowledgeActor, resource_id: str, query: str, top_k: int, call_id: str
    ) -> list[dict]: ...


def build_provider(config: PlatformKnowledgeConf) -> PlatformKnowledgeProvider:
    if config.mode == "mock":
        from bisheng.workflow.domain.clients.platform_knowledge_mock import MockPlatformKnowledgeProvider

        return MockPlatformKnowledgeProvider(config)
    if config.mode == "real":
        from bisheng.workflow.domain.clients.platform_knowledge_real import RealPlatformKnowledgeProvider

        return RealPlatformKnowledgeProvider(config)
    raise PlatformKnowledgeNotReadyError()
