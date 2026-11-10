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
    if config.mode != "mock":
        # TODO [F120][EXT-01] 确认正式资源契约后装配真实目录。
        # TODO [F120][EXT-02] 按昆联确认的用户授权能力获取限时凭据。
        # TODO [F120][EXT-03] 正式检索及错误合同就绪后装配真实调用。
        raise PlatformKnowledgeNotReadyError()
    from bisheng.workflow.domain.clients.platform_knowledge_mock import MockPlatformKnowledgeProvider

    return MockPlatformKnowledgeProvider(config)
