from bisheng.common.errcode.flow import WorkflowRegistrationConflict
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.workflow.application import platform_agent, platform_knowledge
from bisheng.workflow.application.kunlian_workflow_management import is_enrolled, mock_scope, workflow_scope
from bisheng.workflow.domain.repositories.platform_node_publication import PlatformNodePublication
from bisheng.workflow.domain.schemas.platform_agent import uses_platform_agent
from bisheng.workflow.domain.schemas.platform_knowledge import uses_platform_knowledge
from bisheng.workflow.domain.services.kunlian_descriptor import prepare_descriptor


async def publish_registered(repository, user, scope, workflow_id, version_id, validate):
    with tenant_execution_scope(scope.tenant_id):
        flow, version, revision = repository.candidate(scope, workflow_id, version_id)
        graph = PlatformNodePublication.candidate_graph(version.data)
        validate(flow.name, graph)
        agent = platform_agent.get_service() if uses_platform_agent(graph) else None
        knowledge = platform_knowledge.get_service() if uses_platform_knowledge(graph) else None
        agent_binding = await agent.prepare_publication(user, workflow_id, graph) if agent else {}
        knowledge_binding = await knowledge.prepare_publication(user, workflow_id, graph) if knowledge else {}
        descriptor = prepare_descriptor(flow, version, graph, agent_binding, knowledge_binding)
        if (
            workflow_scope(scope.tenant_id, workflow_id, repository=repository) != scope
            or (agent is not None and agent.current_config != agent.config)
            or (knowledge is not None and knowledge.config_source() != knowledge.config)
        ):
            raise WorkflowRegistrationConflict()

        return repository.publish(
            scope,
            workflow_id,
            version_id,
            revision,
            descriptor,
            agent_binding,
            knowledge_binding,
            verify_scope=lambda created: mock_scope(scope.tenant_id) == scope and is_enrolled(workflow_id, created),
        )
