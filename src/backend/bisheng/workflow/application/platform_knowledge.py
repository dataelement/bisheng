"""昆联知识库检索的服务装配。"""

import asyncio
import time
from copy import deepcopy
from types import SimpleNamespace

from bisheng.common.errcode.flow import (
    PlatformAgentExecutionError,
    PlatformKnowledgeConfigurationError,
    PlatformKnowledgeError,
    PlatformKnowledgeExecutionError,
    PlatformKnowledgePermissionError,
    PlatformKnowledgeTimeoutError,
    PlatformKnowledgeUpstreamError,
)
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.services.config_service import settings
from bisheng.workflow.application.platform_agent import actual_user_from_snapshot as agent_actual_user
from bisheng.workflow.domain.repositories.platform_knowledge_run import KnowledgeRunRepository
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest
from bisheng.workflow.domain.schemas.platform_knowledge import (
    PUBLICATION_KEY,
    graph_nodes,
    node_configuration,
    uses_platform_knowledge,
)
from bisheng.workflow.domain.services.platform_knowledge_service import PlatformKnowledgeService


def get_service():
    return PlatformKnowledgeService(
        config=settings.get_workflow_conf().platform_knowledge,
        config_source=lambda: settings.get_workflow_conf().platform_knowledge,
    )


def public_error(error):
    if isinstance(error, PlatformKnowledgeError):
        return type(error)()
    if isinstance(error, UnAuthorizedError):
        return PlatformKnowledgePermissionError()
    return PlatformKnowledgeUpstreamError()


class KnowledgeRun:
    def __init__(self, service, store, record, owner, login_user):
        self.service = service
        self.store = store
        self.record = record
        self.execution_id = record["execution_id"]
        self.owner = owner
        self.login_user = login_user

    def assert_live(self):
        try:
            self.store.check(self.execution_id, self.owner)
        except Exception:
            raise PlatformKnowledgeExecutionError() from None

    async def authorize(self):
        await asyncio.to_thread(self.assert_live)
        actor = await self.service.authorize(self.login_user, self.record["workflow_id"], self.record["action"])
        if actor.token_version != self.record["token_version"]:
            raise PlatformKnowledgePermissionError()
        if canonical_digest(self.service.config_source().model_dump()) != self.record["environment"]:
            raise PlatformKnowledgeExecutionError()
        return actor

    async def invoke(self, node, lookup, call_id, deadline):
        try:
            budget = self.service.config.retrieve_timeout_seconds if deadline is None else deadline - time.monotonic()
            if budget <= 0:
                raise TimeoutError()
            async with asyncio.timeout(budget):
                actor = await self.authorize()
                return await self.service.retrieve(actor, node, lookup, call_id=call_id)
        except TimeoutError:
            raise PlatformKnowledgeTimeoutError() from None
        except Exception as exc:
            raise public_error(exc) from None

    async def commit(self, node_id, step, deadline=None):
        try:
            budget = self.service.config.retrieve_timeout_seconds if deadline is None else deadline - time.monotonic()
            if budget <= 0:
                raise TimeoutError()
            async with asyncio.timeout(budget):
                await self.authorize()
                await asyncio.to_thread(self.store.commit, self.execution_id, self.owner, node_id, step)
        except TimeoutError:
            raise PlatformKnowledgeTimeoutError() from None
        except Exception as exc:
            raise public_error(exc) from None


def actual_user_from_snapshot(snapshot, user_id):
    try:
        return agent_actual_user(snapshot, user_id)
    except PlatformAgentExecutionError:
        raise PlatformKnowledgePermissionError() from None


def store_for(login_user, workflow_id, session_id):
    return KnowledgeRunRepository(workflow_id, session_id, login_user.tenant_id, login_user.user_id)


def verify_published(service, graph):
    binding = graph.get(PUBLICATION_KEY) or {}
    if (
        binding.get("binding_version") != 1
        or binding.get("graph_digest") != canonical_digest(service.repository.candidate_graph(graph))
        or (binding.get("provider_mode"), binding.get("connection_id"), binding.get("policy_revision"))
        != (service.config.mode, service.config.connection_id, service.config.policy_revision)
        or binding.get("nodes") != {node["id"]: node_configuration(node).model_dump() for node in graph_nodes(graph)}
    ):
        raise PlatformKnowledgeExecutionError()


async def prepare_execution(login_user, workflow_id, session_id, graph, *, published, trial_inputs=None, override=None):
    service = get_service()
    action = "use" if published else "edit"
    frozen = deepcopy(graph) if published else service.repository.candidate_graph(graph)
    if published:
        verify_published(service, frozen)
    if override:
        from bisheng.worker.workflow.redis_callback import RedisCallback

        protected = {
            item["data"]["id"]
            for item in frozen.get("nodes", [])
            if item["data"].get("type") in ("platform_knowledge_retriever", "platform_agent")
        }
        if any(key.split(".", 1)[0] in protected for key in override):
            raise PlatformKnowledgeConfigurationError()
        frozen = RedisCallback.override_nodes_params(frozen, override)
    validation = await service.validate_graph(
        login_user,
        workflow_id,
        frozen,
        action=action,
        trial_inputs=trial_inputs,
    )
    if not validation["valid"] or not validation["nodes"]:
        raise PlatformKnowledgeConfigurationError()
    actor = await service.authorize(login_user, workflow_id, action)
    store = store_for(login_user, workflow_id, session_id)
    record = {
        "graph": frozen,
        "workflow_id": workflow_id,
        "action": action,
        "token_version": actor.token_version,
        "environment": canonical_digest(service.config.model_dump()),
    }
    return frozen, store.create(record)


def claim_execution(login_user, workflow_id, session_id, reference, *, resume=False):
    if not isinstance(reference, dict) or set(reference) != {"execution_id", "dispatch_id"}:
        raise PlatformKnowledgeExecutionError()
    store = store_for(login_user, workflow_id, session_id)
    record = store.current()
    if not record or record["execution_id"] != reference["execution_id"]:
        return None
    service = get_service()
    owner = store.claim(reference, resume=resume)
    return KnowledgeRun(service, store, record, owner, login_user) if owner else None


class BrowserPlatformKnowledgeRuntime:
    public_error = staticmethod(public_error)

    async def prepare(self, login_user, workflow_id, session_id, graph, *, published, execution_snapshot=None):
        stored = get_service().repository.get_workflow(workflow_id)["data"]
        if not uses_platform_knowledge(graph) and not uses_platform_knowledge(stored):
            return None
        if execution_snapshot is not None:
            actual_user_from_snapshot(SimpleNamespace(**execution_snapshot), login_user.user_id)
        target = stored if published else graph
        if not uses_platform_knowledge(target):
            return None
        return await prepare_execution(login_user, workflow_id, session_id, target, published=published)

    async def resume(self, login_user, workflow_id, session_id, execution_id):
        service = get_service()
        store = store_for(login_user, workflow_id, session_id)
        record = store.current()
        if not record or record["execution_id"] != execution_id:
            raise PlatformKnowledgeExecutionError()
        actor = await service.authorize(login_user, workflow_id, record["action"])
        if actor.token_version != record["token_version"]:
            raise PlatformKnowledgePermissionError()
        if canonical_digest(service.config_source().model_dump()) != record["environment"]:
            raise PlatformKnowledgeExecutionError()
        return store.resume(execution_id)

    def abort(self, login_user, workflow_id, session_id, execution_id):
        store_for(login_user, workflow_id, session_id).stop(execution_id)
