"""昆联平台大模型服务装配入口。"""

from bisheng.common.services.config_service import settings
from bisheng.workflow.domain.services.platform_llm_service import PlatformLLMService


def get_service() -> PlatformLLMService:
    return PlatformLLMService(config=settings.get_workflow_conf().platform_llm)
