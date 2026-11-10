"""昆联知识库目录、配置校验及检索编排。"""

import asyncio
import json
from collections import defaultdict
from uuid import uuid4

from bisheng.common.errcode.flow import (
    PlatformAgentConfigurationError,
    PlatformAgentError,
    PlatformKnowledgeConfigurationError,
    PlatformKnowledgeError,
    PlatformKnowledgeOutputError,
    PlatformKnowledgeTimeoutError,
    PlatformKnowledgeUpstreamError,
)
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.user.application.runtime_identity import read_current_person_facts
from bisheng.workflow.domain.clients.platform_knowledge import build_provider
from bisheng.workflow.domain.repositories.platform_agent import PlatformAgentRepository
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest
from bisheng.workflow.domain.schemas.platform_knowledge import (
    MAX_TOP_K,
    MISSING,
    KnowledgeActor,
    KnowledgeHit,
    VariableQuestion,
    graph_nodes,
    node_configuration,
    resolve_question,
)


class PlatformKnowledgeService:
    def __init__(self, *, config, repository=None, provider=None, identity_reader=None, config_source=None):
        self.config = config
        self.repository = repository or PlatformAgentRepository()
        self._provider = provider
        self.identity_reader = identity_reader or read_current_person_facts
        self.config_source = config_source or (lambda: self.config)

    @property
    def provider(self):
        return self._provider or build_provider(self.config)

    async def authorize(self, login_user, workflow_id, action="edit"):
        flow = self.repository.get_workflow(workflow_id)
        if flow["tenant_id"] != login_user.tenant_id or flow.get("flow_type", 10) != 10:
            raise UnAuthorizedError()
        facts = (await self.identity_reader([login_user.user_id])).get(login_user.user_id, {})
        if facts.get("state") != "active" or facts.get("tenant_id") != login_user.tenant_id:
            raise UnAuthorizedError()
        await require_business_action(login_user, resource_type="workflow", resource_id=workflow_id, action=action)
        return KnowledgeActor(int(login_user.user_id), int(login_user.tenant_id), facts["token_version"])

    async def list_knowledge(self, login_user, workflow_id, cursor=None, name=None):
        actor = await self.authorize(login_user, workflow_id)
        return await self.provider.list_knowledge(actor, cursor, name)

    async def get_knowledge(self, login_user, workflow_id, resource_id):
        actor = await self.authorize(login_user, workflow_id)
        result = await self.provider.get_knowledge(actor, resource_id)
        return {**result, "max_top_k": MAX_TOP_K, "default_top_k": 5}

    async def validate_reference(self, actor, graph, variable):
        # 沿用 Workflow 已有的服务端引用验证规则。
        from bisheng.common.services.config_service import settings
        from bisheng.workflow.domain.services.platform_agent_service import PlatformAgentService

        service = PlatformAgentService(config=settings.get_workflow_conf().platform_agent)
        try:
            await service.validate_reference(actor, graph, variable)
        except (PlatformAgentConfigurationError, ValueError):
            raise PlatformKnowledgeConfigurationError() from None
        except PlatformAgentError:
            raise PlatformKnowledgeUpstreamError() from None

    async def validate_graph(self, login_user, workflow_id, graph, node_id=None, *, action="edit", trial_inputs=None):
        actor = await self.authorize(login_user, workflow_id, action)
        nodes = [node for node in graph_nodes(graph) if node_id is None or node["id"] == node_id]
        if node_id is not None and not nodes:
            raise PlatformKnowledgeConfigurationError()
        upstream = defaultdict(set)
        try:
            for edge in graph.get("edges", []):
                upstream[edge["target"]].add(edge["source"])
        except (KeyError, TypeError):
            raise PlatformKnowledgeConfigurationError() from None
        issues, materials = [], {}
        for node in nodes:
            try:
                config = node_configuration(node)
                question = config.user_question
                if isinstance(question, VariableQuestion) and question.variable not in (trial_inputs or ()):
                    source_id = question.variable.split(".", 1)[0]
                    if source_id not in self._upstream_nodes(upstream, node["id"]):
                        raise PlatformKnowledgeConfigurationError()
                    await self.validate_reference(actor, graph, question.variable)
                await self.provider.check_use(actor, config.knowledge.resource_id)
                materials[node["id"]] = config.model_dump()
            except PlatformKnowledgeConfigurationError as error:
                issues.append({"node_id": node["id"], "field": "user_question", "code": error.Code})
        return {"valid": not issues, "issues": issues, "nodes": materials}

    @staticmethod
    def _upstream_nodes(upstream, node_id):
        visited = {node_id}
        pending = list(upstream[node_id])
        while pending:
            source = pending.pop()
            if source not in visited:
                visited.add(source)
                pending.extend(upstream[source])
        return visited - {node_id}

    async def prepare_publication(self, login_user, workflow_id, graph):
        validation = await self.validate_graph(login_user, workflow_id, graph, action="publish")
        if not validation["valid"]:
            raise PlatformKnowledgeConfigurationError()
        return {
            "binding_version": 1,
            "graph_digest": canonical_digest(graph),
            "provider_mode": self.config.mode,
            "connection_id": self.config.connection_id,
            "policy_revision": self.config.policy_revision,
            "nodes": validation["nodes"],
        }

    async def retrieve(self, actor, node, lookup, *, call_id=None):
        config = node_configuration(node)
        query = resolve_question(config, lookup)
        resource = config.knowledge.resource_id
        try:
            async with asyncio.timeout(self.config.retrieve_timeout_seconds):
                await self.provider.check_use(actor, resource)
                rows = (
                    await self.provider.retrieve(actor, resource, query, config.top_k, call_id or uuid4().hex)
                    if query
                    else []
                )
        except TimeoutError:
            raise PlatformKnowledgeTimeoutError() from None
        except PlatformKnowledgeError:
            raise
        except Exception:
            raise PlatformKnowledgeUpstreamError() from None
        return self.normalize(rows, resource, config.top_k)

    def normalize(self, rows, resource, top_k):
        try:
            if not isinstance(rows, list) or len(rows) > top_k:
                raise ValueError
            if len(json.dumps(rows, ensure_ascii=False, allow_nan=False).encode()) > self.config.max_payload_bytes:
                raise ValueError
            hits = [KnowledgeHit.model_validate(row) for row in rows]
            if any(
                hit.resource_id != resource
                or not all(value.strip() for value in (hit.document_id, hit.chunk_id, hit.text))
                for hit in hits
            ):
                raise ValueError
        except (TypeError, ValueError):
            raise PlatformKnowledgeOutputError() from None
        result, citations, text = [], [], []
        for hit in hits:
            source = hit.model_dump(exclude={"text", "score", "resource_id"}, exclude_none=True)
            source.update(provider="kunlian", connection_id=self.config.connection_id, knowledge_id=resource)
            item = {"text": hit.text, "metadata": source}
            if hit.score is not None:
                item["score"] = hit.score
            result.append(item)
            citations.append(source.copy())
            title = hit.document_name or hit.document_id
            text.append(f"{title}{' ' + hit.location if hit.location else ''}\n{hit.text}")
        return {
            "retrieved_result": result,
            "retrieved_text": "\n\n".join(text),
            "citations": citations,
            "hit_count": len(result),
        }


__all__ = ["MISSING", "PlatformKnowledgeService"]
