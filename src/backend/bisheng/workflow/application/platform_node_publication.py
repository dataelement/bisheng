"""在同一候选版本上完成预检、再提交一次发布。"""

from bisheng.common.errcode.flow import (
    PlatformAgentPublicationError,
    PlatformKnowledgeConfigurationError,
    PlatformKnowledgeExecutionError,
)
from bisheng.workflow.application import platform_agent, platform_knowledge
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest, uses_platform_agent
from bisheng.workflow.domain.schemas.platform_knowledge import uses_platform_knowledge


def uses_platform_nodes(graph):
    return uses_platform_agent(graph) or uses_platform_knowledge(graph)


async def publish(login_user, flow_id, version_id):
    knowledge = platform_knowledge.get_service()
    repository = knowledge.repository
    version = repository.get_version(version_id)
    if version["flow_id"] != flow_id:
        raise PlatformKnowledgeConfigurationError()
    graph = repository.candidate_graph(version["data"])
    binding = await knowledge.prepare_publication(login_user, flow_id, graph)
    agent = platform_agent.get_service() if uses_platform_agent(graph) else None
    agent_binding = await agent.prepare_publication(login_user, flow_id, graph) if agent else {}
    if knowledge.config != knowledge.config_source():
        raise PlatformKnowledgeExecutionError()
    if agent and agent.current_config != agent.config:
        raise PlatformKnowledgeExecutionError()
    try:
        return repository.publish_validated_graph(
            flow_id,
            version_id,
            canonical_digest(graph),
            agent_binding,
            knowledge_binding=binding,
        )
    except PlatformAgentPublicationError:
        raise PlatformKnowledgeExecutionError() from None
