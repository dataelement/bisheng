"""平台 Agent 的统一授权、资源校验和运行编排。"""

import asyncio
import json
import re
import time
from copy import deepcopy
from weakref import WeakKeyDictionary

from loguru import logger

from bisheng.common.errcode.flow import (
    PlatformAgentConfigurationError,
    PlatformAgentEnvironmentError,
    PlatformAgentError,
    PlatformAgentExecutionError,
    PlatformAgentNonterminalError,
    PlatformAgentOutputError,
    PlatformAgentPermissionError,
    PlatformAgentUnknownError,
    PlatformAgentUpstreamError,
    PlatformAgentVersionError,
)
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.permission import InvalidCatalogActionError, PermissionDeniedError
from bisheng.common.errcode.tenant_resolver import TokenVersionMismatchError
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.user.application.runtime_identity import read_current_person_facts
from bisheng.workflow.domain.clients.platform_agent import build_provider
from bisheng.workflow.domain.repositories.platform_agent import LOCAL_TERMINAL, REMOTE_TERMINAL, PlatformAgentRepository
from bisheng.workflow.domain.schemas.platform_agent import (
    PUBLICATION_KEY,
    AgentInteraction,
    AgentInteractionReference,
    AgentReference,
    VerifiedAgentActor,
    canonical_digest,
    interaction_node_ids,
    long_task_resume_node_ids,
    node_configuration,
    platform_nodes,
    resolve_inputs,
    uses_agent_interaction,
    validate_schema,
    validate_value,
)

_MOCK_LONG_SLOTS = WeakKeyDictionary()


class PlatformAgentService:
    def __init__(
        self,
        *,
        config,
        repository=None,
        provider=None,
        identity_reader=None,
        config_source=None,
        long_pause=asyncio.sleep,
        long_wake=None,
        enable_long_tasks=False,
        enable_interactions=False,
        enable_long_task_resume=False,
    ):
        self.config = config
        self.repository = repository or PlatformAgentRepository()
        self._provider = provider
        self.identity_reader = identity_reader
        self.config_source = config_source
        self.long_pause = long_pause
        self.long_wake = long_wake
        self.enable_long_tasks = enable_long_tasks
        self.enable_interactions = enable_interactions
        self.enable_long_task_resume = enable_long_task_resume

    @property
    def current_config(self):
        return self.config_source() if self.config_source else self.config

    @property
    def interaction_available(self):
        return self.config.mode == self.current_config.mode == "mock" and self.enable_long_tasks and self.enable_interactions

    @property
    def long_task_resume_available(self):
        return (
            self.config.mode == self.current_config.mode == "mock"
            and self.enable_long_tasks
            and self.enable_long_task_resume
        )

    @staticmethod
    def browser_origin(login_user):
        source = getattr(login_user, "auth_source", None) or "local"
        if source == "kunlian":
            reference = getattr(login_user, "_runtime_credential_reference", None) or {}
            binding_id = reference.get("binding_id")
            if not binding_id:
                raise UnAuthorizedError()
            return {"source": source, "binding_id": binding_id}
        return {"source": source}

    @property
    def provider(self):
        if self.enable_interactions and self.enable_long_tasks:
            return self._provider or build_provider(self.config, enable_interactions=True)
        return self._provider or build_provider(self.config)

    async def authorize(self, login_user, workflow_id, action="edit"):
        flow = self.repository.get_workflow(workflow_id)
        if flow["tenant_id"] != login_user.tenant_id or flow.get("flow_type", 10) != 10:
            raise UnAuthorizedError()
        facts = (await (self.identity_reader or read_current_person_facts)([login_user.user_id])).get(
            login_user.user_id, {}
        )
        if facts.get("state") != "active" or facts.get("tenant_id") != login_user.tenant_id:
            raise UnAuthorizedError()
        await require_business_action(login_user, resource_type="workflow", resource_id=workflow_id, action=action)
        return VerifiedAgentActor(int(login_user.user_id), int(login_user.tenant_id), facts["token_version"])

    async def list_agents(self, login_user, workflow_id, cursor=None):
        actor = await self.authorize(login_user, workflow_id)
        return await self.provider.list_agents(actor, cursor)

    async def get_version(self, login_user, workflow_id, agent_id, version_id):
        actor = await self.authorize(login_user, workflow_id)
        version = await self.provider.get_version(actor, AgentReference(agent_id=agent_id, version_id=version_id))
        validate_schema(version.input_schema, root_object=True)
        validate_schema(version.output_schema)
        return {
            **version.model_dump(),
            "provider_mode": self.config.mode,
            "policy_revision": self.config.policy_revision,
            "long_tasks_available": self.config.mode == "mock" and self.enable_long_tasks,
            "interaction_available": self.interaction_available,
        }

    async def validate_graph(self, login_user, workflow_id, graph, node_id=None, *, action="edit", trial_inputs=None):
        actor = await self.authorize(login_user, workflow_id, action)
        if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
            raise PlatformAgentConfigurationError()
        issues, materials = [], {}
        for node in platform_nodes(graph):
            if node_id is not None and node.get("id") != node_id:
                continue
            try:
                configuration = node_configuration(node)
                if configuration.agent_ref is None or not node.get("id") or node["id"] in materials:
                    raise PlatformAgentConfigurationError()
                version = await self.provider.get_version(actor, configuration.agent_ref)
                if version.ref != configuration.agent_ref:
                    raise PlatformAgentVersionError()
                if configuration.allow_interaction:
                    if not (
                        self.enable_interactions
                        and self.enable_long_tasks
                        and self.config.mode == "mock"
                        and configuration.execution_mode == "async"
                        and version.supports_async
                        and version.supports_interaction
                    ):
                        raise PlatformAgentConfigurationError()
                    interaction_node_ids(graph)
                if configuration.execution_mode == "async" and not (self.enable_long_tasks and version.supports_async):
                    raise PlatformAgentVersionError()
                await self.provider.check_use(actor, configuration.agent_ref)
                validate_schema(version.input_schema, root_object=True)
                validate_schema(version.output_schema)
                for required in version.input_schema.get("required", []):
                    if required not in configuration.input_bindings:
                        raise PlatformAgentConfigurationError()
                properties = version.input_schema.get("properties", {})
                for field, binding in configuration.input_bindings.items():
                    if field not in properties and version.input_schema.get("additionalProperties") is False:
                        raise PlatformAgentConfigurationError()
                    if binding.source == "constant":
                        if "value" not in binding.model_fields_set:
                            raise PlatformAgentConfigurationError()
                        additional = version.input_schema.get("additionalProperties", {})
                        validate_value(
                            binding.value, properties.get(field, additional if isinstance(additional, dict) else {})
                        )
                    elif not binding.variable or "." not in binding.variable:
                        raise PlatformAgentConfigurationError()
                    elif trial_inputs is None or binding.variable not in trial_inputs:
                        await self.validate_reference(actor, graph, binding.variable)
                if all(binding.source == "constant" for binding in configuration.input_bindings.values()):
                    resolve_inputs(configuration.input_bindings, version.input_schema, lambda _: None)
                materials[node["id"]] = {
                    "ref": version.ref.model_dump(),
                    "schema_digest": canonical_digest([version.input_schema, version.output_schema]),
                    "input_schema": deepcopy(version.input_schema),
                    "output_schema": deepcopy(version.output_schema),
                }
                if configuration.execution_mode == "async":
                    materials[node["id"]]["execution_mode"] = "async"
                if configuration.allow_interaction:
                    materials[node["id"]]["allow_interaction"] = True
            except PlatformAgentConfigurationError:
                issues.append({"node_id": node.get("id"), "field": "input_bindings", "code": 10551})
        platform_ids = {node["id"] for node in platform_nodes(graph)}
        for item in graph.get("nodes", []):
            target = item.get("data", {})
            for group in target.get("group_params", []):
                for param in group.get("params", []):
                    for reference in self.parameter_references(param):
                        if reference.split(".", 1)[0] not in platform_ids:
                            continue
                        try:
                            await self.validate_reference(actor, graph, reference)
                        except PlatformAgentConfigurationError:
                            issues.append({"node_id": target.get("id"), "field": param.get("key"), "code": 10551})
        return {"valid": not issues, "issues": issues, "nodes": materials, "provider_mode": self.config.mode}

    @staticmethod
    def parameter_references(param):
        value = param.get("value")
        if param.get("type") in {"var_textarea", "var_textarea_file", "image_prompt"}:
            pending = [value]
            while pending:
                item = pending.pop()
                if isinstance(item, str):
                    yield from re.findall(r"\{\{#(.*?)#\}\}", item)
                elif isinstance(item, dict):
                    pending.extend(item.values())
                elif isinstance(item, list):
                    pending.extend(item)
        elif param.get("type") in {"var_select", "user_question"}:
            yield from ([value] if isinstance(value, str) else (value or []))
        elif param.get("type") == "code_input" and isinstance(value, list):
            yield from (
                item["value"] for item in value if item.get("type") == "ref" and isinstance(item.get("value"), str)
            )

    async def validate_reference(self, actor, graph, path):
        source_id, key = path.split(".", 1)
        source = next(
            (item.get("data", {}) for item in graph.get("nodes", []) if item.get("data", {}).get("id") == source_id),
            None,
        )
        if source is None:
            raise PlatformAgentConfigurationError()
        base, _, field = key.partition("#")
        if source.get("type") == "platform_knowledge_retriever":
            from bisheng.workflow.domain.schemas.platform_knowledge import OUTPUT_KEYS

            if field or base not in OUTPUT_KEYS:
                raise PlatformAgentConfigurationError()
            return
        if source.get("type") == "platform_agent":
            configuration = node_configuration(source)
            if base != "result" or configuration.agent_ref is None:
                raise PlatformAgentConfigurationError()
            version = await self.provider.get_version(actor, configuration.agent_ref)
            schema = version.output_schema
            if field and not (
                field in schema.get("properties", {}) or (schema.get("type") == "array" and field.isdigit())
            ):
                raise PlatformAgentConfigurationError()
            return
        for group in source.get("group_params", []):
            for param in group.get("params", []):
                if param.get("key") == base:
                    if base in {"custom_variables", "preset_question"} and field:
                        if any(item.get("key") == field for item in param.get("value", [])):
                            return
                    elif param.get("global") or param.get("type") in {"var", "form", "code_output"}:
                        return
                if param.get("type") in {"form", "code_output"} and isinstance(param.get("value"), list):
                    if any(
                        base
                        in {item.get("key"), item.get("file_path"), item.get("file_content"), item.get("image_file")}
                        for item in param["value"]
                    ):
                        return
        raise PlatformAgentConfigurationError()

    async def publish(self, login_user, workflow_id, version_id):
        version = self.repository.get_version(version_id)
        if version["flow_id"] != workflow_id:
            raise PlatformAgentConfigurationError()
        graph = self.repository.candidate_graph(version["data"])
        binding = await self.prepare_publication(login_user, workflow_id, graph)
        return self.repository.publish_validated_graph(workflow_id, version_id, canonical_digest(graph), binding)

    async def prepare_publication(self, login_user, workflow_id, graph):
        validation = await self.validate_graph(login_user, workflow_id, graph, action="publish")
        if not validation["valid"]:
            raise PlatformAgentConfigurationError()
        binding = {
            "binding_version": 1,
            "graph_digest": canonical_digest(graph),
            "provider_mode": self.config.mode,
            "connection_id": self.config.connection_id,
            "policy_revision": self.config.policy_revision,
            "nodes": validation["nodes"],
        }
        if self.repository.environment(self.current_config) != self.repository.environment(self.config):
            raise PlatformAgentEnvironmentError()
        return binding

    async def admit(
        self,
        login_user,
        workflow_id,
        session_id,
        graph,
        entry_kind,
        *,
        override=None,
        trial_inputs=None,
        interaction_session=False,
        long_task_resume_session=False,
    ):
        actor = await self.authorize(login_user, workflow_id, "edit" if entry_kind == "DEBUG" else "use")
        _ = self.provider  # 禁用及真实未就绪必须在写队列前拒绝。
        if len(json.dumps(graph, ensure_ascii=False).encode()) > self.config.max_payload_bytes:
            raise PlatformAgentConfigurationError()
        if long_task_resume_session:
            if not self.long_task_resume_available or entry_kind != "PUBLISHED" or not session_id or override:
                raise PlatformAgentConfigurationError()
            long_task_resume_node_ids(graph)
        if uses_agent_interaction(graph):
            if not (
                self.enable_interactions
                and self.enable_long_tasks
                and self.config.mode == "mock"
                and entry_kind == "PUBLISHED"
                and interaction_session
                and session_id
                and not override
            ):
                raise PlatformAgentConfigurationError()
            _, agent = interaction_node_ids(graph)
            material = graph.get(PUBLICATION_KEY, {}).get("nodes", {}).get(agent, {})
            if material.get("allow_interaction") is not True:
                raise PlatformAgentConfigurationError()
        if entry_kind == "DEBUG":
            graph = self.repository.candidate_graph(graph)
            validation = await self.validate_graph(login_user, workflow_id, graph, trial_inputs=trial_inputs)
            if not validation["valid"]:
                raise PlatformAgentConfigurationError()
            graph[PUBLICATION_KEY] = {
                "binding_version": 1,
                "graph_digest": canonical_digest(graph),
                "provider_mode": self.config.mode,
                "connection_id": self.config.connection_id,
                "policy_revision": self.config.policy_revision,
                "nodes": validation["nodes"],
            }
        if override:
            protected = {node["id"] for node in platform_nodes(graph)}
            if PUBLICATION_KEY in override or any(key.split(".", 1)[0] in protected for key in override):
                raise PlatformAgentConfigurationError()
            graph = deepcopy(graph)
            for node in graph.get("nodes", []):
                replacements = override.get(node.get("data", {}).get("id"), {})
                if not isinstance(replacements, dict):
                    raise PlatformAgentConfigurationError()
                for group in node.get("data", {}).get("group_params", []):
                    for param in group.get("params", []):
                        if param.get("key") in replacements:
                            param["value"] = replacements[param["key"]]
        binding = graph.get(PUBLICATION_KEY)
        if entry_kind != "DEBUG" and not binding:
            raise PlatformAgentVersionError()
        if binding and set(binding.get("nodes", {})) != {node["id"] for node in platform_nodes(graph)}:
            raise PlatformAgentVersionError()
        if binding and binding.get("provider_mode") != self.config.mode:
            raise PlatformAgentEnvironmentError()
        if binding and (binding.get("connection_id"), binding.get("policy_revision")) != (
            self.config.connection_id,
            self.config.policy_revision,
        ):
            raise PlatformAgentEnvironmentError()
        options = {"browser_origin": self.browser_origin(login_user)} if (
            long_task_resume_session or uses_agent_interaction(graph)
        ) else {}
        if long_task_resume_session:
            options["long_task_resume"] = True
        return self.repository.prepare_execution(workflow_id, session_id, actor, graph, self.config, entry_kind, **options)

    async def invoke_node(self, login_user, workflow_id, dispatch, node, ordinal, lookup):
        if node_configuration(node).execution_mode == "async":
            return await self.invoke_long_node(login_user, workflow_id, dispatch, node, ordinal, lookup)
        # 总预算覆盖重新授权、版本检查和 invoke。不为 POST 配置自动重试。
        deadline = time.time() + self.config.invoke_timeout_seconds
        reserved = False
        try:
            async with asyncio.timeout(self.config.invoke_timeout_seconds):
                actor = await self.authorize(
                    login_user,
                    workflow_id,
                    "edit" if self.repository.get_execution(dispatch.execution_id)["entry_kind"] == "DEBUG" else "use",
                )
                execution = self.repository.get_execution(dispatch.execution_id)
                if (execution["user_id"], execution["tenant_id"]) != (actor.user_id, actor.tenant_id):
                    raise UnAuthorizedError()
                if execution["actor_reference"].get("token_version") != actor.token_version:
                    raise TokenVersionMismatchError()
                if execution["actor_reference"].get("environment") != self.repository.environment(self.current_config):
                    raise PlatformAgentEnvironmentError()
                configuration = node_configuration(node)
                if configuration.agent_ref is None:
                    raise PlatformAgentConfigurationError()
                provider = self.provider
                version = await provider.get_version(actor, configuration.agent_ref)
                if version.ref != configuration.agent_ref:
                    raise PlatformAgentVersionError()
                await provider.check_use(actor, configuration.agent_ref)
                validate_schema(version.output_schema)
                binding = execution["graph_snapshot"].get(PUBLICATION_KEY, {}).get("nodes", {}).get(node["id"])
                if binding and (
                    binding["ref"] != version.ref.model_dump()
                    or binding["schema_digest"] != canonical_digest([version.input_schema, version.output_schema])
                ):
                    raise PlatformAgentVersionError()
                inputs = resolve_inputs(configuration.input_bindings, version.input_schema, lookup)
                if len(json.dumps(inputs, ensure_ascii=False).encode()) > self.config.max_payload_bytes:
                    raise PlatformAgentConfigurationError()
                digest = canonical_digest([version.ref.model_dump(), inputs, actor.user_id, actor.tenant_id])
                self.repository.reserve_call(dispatch, node["id"], ordinal, digest, version.ref.model_dump(), deadline)
                reserved = True
                result = await provider.invoke(
                    actor, version.ref, inputs, f"{dispatch.execution_id}:{node['id']}:{ordinal}"
                )
                self.repository.record_response(dispatch, node["id"], ordinal, result.agent_run_id)
                if result.ref != version.ref:
                    raise PlatformAgentVersionError()
                if result.status in {"RUNNING", "INPUT"}:
                    raise PlatformAgentNonterminalError()
                if result.status != "SUCCEEDED":
                    raise PlatformAgentUpstreamError()
                if len(json.dumps(result.output, ensure_ascii=False).encode()) > self.config.max_payload_bytes:
                    raise PlatformAgentOutputError()
                validate_value(result.output, version.output_schema, output=True)
                return deepcopy(result.output)
        except TimeoutError:
            if reserved:
                self.repository.finish_call(dispatch, node["id"], ordinal, "UNKNOWN")
            raise PlatformAgentUnknownError() from None
        except Exception as error:
            if reserved:
                self.repository.finish_call(
                    dispatch,
                    node["id"],
                    ordinal,
                    "UNKNOWN" if isinstance(error, PlatformAgentNonterminalError) else "FAILED",
                )
            if isinstance(error, PlatformAgentError | UnAuthorizedError | TokenVersionMismatchError):
                raise
            raise PlatformAgentUpstreamError() from None

    async def _long_actor(self, login_user, execution):
        # TODO [F124][EXT-04] 正式动作鉴权须使用同一实际用户的可信委托。
        if (execution["user_id"], execution["tenant_id"]) != (login_user.user_id, login_user.tenant_id):
            raise UnAuthorizedError()
        actor = await self.authorize(
            login_user, execution["workflow_id"], "edit" if execution["entry_kind"] == "DEBUG" else "use"
        )
        reference = execution["actor_reference"]
        if reference.get("token_version") != actor.token_version:
            raise TokenVersionMismatchError()
        if reference.get("environment") != self.repository.environment(self.current_config):
            raise PlatformAgentEnvironmentError()
        return actor

    async def _long_request(self, deadline, operation, *args):
        remaining = deadline - self.repository.clock()
        if remaining <= 0:
            raise TimeoutError()
        async with asyncio.timeout(min(remaining, self.config.invoke_timeout_seconds)):
            return await operation(*args)

    async def invoke_long_node(
        self, login_user, workflow_id, dispatch, node, ordinal, lookup, notify=None, *,
        wait_checkpoint=None, resume_checkpoint=None,
    ):
        if self.config.mode != "mock" or not self.enable_long_tasks:
            raise PlatformAgentEnvironmentError()
        slots = _MOCK_LONG_SLOTS.setdefault(asyncio.get_running_loop(), asyncio.Semaphore(8))
        if slots.locked():
            raise PlatformAgentExecutionError()
        async with slots:
            return await self._run_long(
                login_user, workflow_id, dispatch, node, ordinal, lookup, notify, wait_checkpoint, resume_checkpoint
            )

    async def _run_long(
        self, login_user, workflow_id, dispatch, node, ordinal, lookup, notify, wait_checkpoint, resume_checkpoint
    ):
        repo = self.repository
        start = repo.clock()
        deadline = start + 30
        start_deadline = min(deadline, start + self.config.invoke_timeout_seconds)
        key = f"{node['id']}:{ordinal}"
        call_id = f"{dispatch.execution_id}:{key}"
        execution = repo.get_execution(dispatch.execution_id)
        if execution["workflow_id"] != workflow_id or self.config.mode != "mock":
            raise PlatformAgentEnvironmentError()
        resumable = resume_checkpoint is not None
        entry = execution["dispatches"][dispatch.dispatch_id]
        if resumable != bool(entry.get("long_task_resume")) or (resumable and not self.long_task_resume_available):
            raise PlatformAgentEnvironmentError()
        reserve_options = {"resume_checkpoint": resume_checkpoint} if resumable else {}
        provider = self.provider
        conf = node_configuration(node)
        ref = conf.agent_ref
        if ref is None or conf.allow_interaction != (wait_checkpoint is not None):
            raise PlatformAgentConfigurationError()
        if conf.allow_interaction and (not self.enable_interactions or execution["entry_kind"] != "PUBLISHED"):
            raise PlatformAgentConfigurationError()
        reserved = False
        try:
            actor = await self._long_request(start_deadline, self._long_actor, login_user, execution)
            version = await self._long_request(start_deadline, provider.get_version, actor, ref)
            await self._long_request(start_deadline, provider.check_use, actor, ref)
            binding = execution["graph_snapshot"].get(PUBLICATION_KEY, {}).get("nodes", {}).get(node["id"])
            if (
                version.ref != ref
                or not version.supports_async
                or (
                    conf.allow_interaction
                    and (
                        not version.supports_interaction or not binding or binding.get("allow_interaction") is not True
                    )
                )
                or (
                    binding
                    and (
                        binding.get("execution_mode") != "async"
                        or binding.get("ref") != ref.model_dump()
                        or binding.get("schema_digest")
                        != canonical_digest([version.input_schema, version.output_schema])
                    )
                )
            ):
                raise PlatformAgentVersionError()
            inputs = resolve_inputs(conf.input_bindings, version.input_schema, lookup)
            if len(json.dumps(inputs, ensure_ascii=False).encode()) > self.config.max_payload_bytes:
                raise PlatformAgentConfigurationError()
            digest = canonical_digest(
                [ref.model_dump(), inputs, actor.user_id, actor.tenant_id, self.config.connection_id]
            )
            repo.reserve_long_call(dispatch, key, digest, ref.model_dump(), start, start_deadline, deadline, **reserve_options)
            reserved = True
            if not repo.permit_long_start(dispatch, key):
                raise TimeoutError()
            try:
                # TODO [F126][EXT-01] 正式启动的幂等键和查回条件待确认。
                observation = await self._long_request(start_deadline, provider.start, actor, ref, inputs, call_id)
            except (TimeoutError, ConnectionError, PlatformAgentUpstreamError):
                if not resumable:
                    repo.observe_long(dispatch.execution_id, key, dispatch=dispatch, remote_state="START_UNKNOWN")
                observation = None
            except PlatformAgentError:
                repo.observe_long(dispatch.execution_id, key, dispatch=dispatch, remote_state="START_REJECTED")
                raise
            if resumable:
                repo.save_long_task_resume_wait(dispatch, key, observation)
                return None
            if observation is not None:
                if wait_checkpoint is not None and observation.status == "WAITING_INPUT":
                    repo.save_long_wait(dispatch, key, observation, wait_checkpoint)
                    return None
                repo.observe_long(dispatch.execution_id, key, dispatch=dispatch, observation=observation)
            return await self._poll_long(
                login_user, dispatch, key, ref, version.output_schema, provider, notify, wait_checkpoint
            )
        except TimeoutError:
            if not reserved:
                repo.reserve_long_call(
                    dispatch,
                    key,
                    canonical_digest([ref.model_dump(), "START_TIMEOUT"]),
                    ref.model_dump(),
                    start,
                    start_deadline,
                    deadline,
                    **reserve_options,
                )
            reason = repo.timeout_long(dispatch, key)
            self.notify_long(dispatch.execution_id, key, notify)
            self.wake_long(execution["tenant_id"], dispatch.execution_id, key)
            if reason == "START_TIMEOUT":
                raise PlatformAgentExecutionError() from None
            raise PlatformAgentUnknownError() from None
        except Exception as error:
            if reserved:
                reason = (
                    "FORBIDDEN" if isinstance(error, (UnAuthorizedError, TokenVersionMismatchError)) else "RUN_FAILED"
                )
                repo.close_long(dispatch, key, "FAILED", reason)
                self.notify_long(dispatch.execution_id, key, notify)
            if isinstance(error, (PlatformAgentError, UnAuthorizedError, TokenVersionMismatchError)):
                raise
            raise PlatformAgentUpstreamError() from None

    async def submit_interaction_answer(
        self, login_user, execution_id, key, interaction_id, revision, submission_id, answer
    ):
        self._require_interactions()
        task = self.repository.long_snapshot(execution_id, key)
        actor = await self._long_actor(login_user, task)
        await self.provider.check_use(actor, AgentReference.model_validate(task["ref"]))
        receipt = self.repository.accept_interaction_answer(
            execution_id, key, actor, interaction_id, revision, submission_id, answer
        )
        if receipt["phase"] == "SUBMIT_QUEUED":
            self.wake_long(task["tenant_id"], execution_id, key)
        return receipt

    def _require_interactions(self):
        if self.config.mode != "mock" or not (self.enable_long_tasks and self.enable_interactions):
            raise PlatformAgentEnvironmentError()

    async def resume_long_interaction(self, login_user, dispatch, key, notify=None):
        self._require_interactions()
        repo = self.repository
        execution = repo.get_execution(dispatch.execution_id)
        task = repo.long_snapshot(dispatch.execution_id, key)
        interaction = task.get("interaction", {})
        if (
            interaction.get("phase") != "SUBMIT_QUEUED"
            or interaction.get("dispatch_id") != dispatch.dispatch_id
            or not task["run_id"]
        ):
            raise PlatformAgentExecutionError()
        deadline = task["deadline"]
        ref = AgentReference.model_validate(task["ref"])
        form = AgentInteraction.model_validate(interaction["form"])
        binding = execution["graph_snapshot"][PUBLICATION_KEY]["nodes"][interaction["snapshot"]["agent_node"]]
        provider = self.provider

        async def send(*, replay=False):
            actor = await self._long_request(deadline, self._long_actor, login_user, task)
            await self._long_request(deadline, provider.check_use, actor, ref)
            repo.permit_interaction_submit(dispatch, key, replay=replay)

            async def handoff():
                # 停止仍可在传输接手前生效。接手后的回执须重新通过行锁判定。
                repo.confirm_interaction_handoff(dispatch, key)
                return await provider.submit_interaction(
                    actor, ref, task["run_id"], form, interaction["answer"], interaction["remote_key"]
                )

            try:
                return await self._long_request(deadline, handoff)
            except (TimeoutError, ConnectionError, PlatformAgentUpstreamError):
                repo.mark_interaction_unknown(dispatch, key)
                self.notify_long(dispatch.execution_id, key, notify)
                return None

        try:
            actor = await self._long_request(deadline, self._long_actor, login_user, task)
            version = await self._long_request(deadline, provider.get_version, actor, ref)
            if (
                binding.get("allow_interaction") is not True
                or binding.get("execution_mode") != "async"
                or binding.get("ref") != ref.model_dump()
                or version.ref != ref
                or not version.supports_async
                or not version.supports_interaction
                or binding["schema_digest"] != canonical_digest([version.input_schema, version.output_schema])
            ):
                raise PlatformAgentVersionError()
            receipt = await send()
            replayed = False
            while receipt is None:
                actor = await self._long_request(deadline, self._long_actor, login_user, task)
                try:
                    receipt = await self._long_request(
                        deadline,
                        provider.lookup_submission,
                        actor,
                        ref,
                        task["run_id"],
                        form,
                        interaction["remote_key"],
                    )
                except (TimeoutError, ConnectionError, PlatformAgentUpstreamError):
                    await self.long_pause(min(1, max(0, deadline - repo.clock())))
                    continue
                if receipt is not None:
                    break
                if not replayed and getattr(provider, "supports_interaction_replay", False) is True:
                    replayed = True
                    receipt = await send(replay=True)
                if receipt is None:
                    await self.long_pause(min(1, max(0, deadline - repo.clock())))
            if not repo.record_interaction_receipt(dispatch, key, receipt):
                raise PlatformAgentUpstreamError()
            self.notify_long(dispatch.execution_id, key, notify)
            return await self._poll_long(
                login_user, dispatch, key, ref, binding["output_schema"], provider, notify, resuming_form=form
            )
        except TimeoutError:
            repo.timeout_long(dispatch, key)
            self.notify_long(dispatch.execution_id, key, notify)
            self.wake_long(task["tenant_id"], dispatch.execution_id, key)
            raise PlatformAgentUnknownError() from None
        except Exception as error:
            reason = (
                "FORBIDDEN"
                if isinstance(
                    error,
                    (UnAuthorizedError, TokenVersionMismatchError, PlatformAgentPermissionError, PermissionDeniedError),
                )
                else "RUN_FAILED"
            )
            repo.close_long(dispatch, key, "FAILED", reason)
            self.notify_long(dispatch.execution_id, key, notify)
            if isinstance(error, (PlatformAgentError, UnAuthorizedError, TokenVersionMismatchError)):
                raise
            raise PlatformAgentUpstreamError() from None

    async def _poll_long(
        self, login_user, dispatch, key, ref, schema, provider, notify, wait_checkpoint=None, *, resuming_form=None
    ):
        repo = self.repository
        call_id = f"{dispatch.execution_id}:{key}"
        delay = 0.25
        previous_summary = None
        while True:
            task = repo.long_snapshot(dispatch.execution_id, key)
            if task["local_state"] in LOCAL_TERMINAL:
                raise PlatformAgentExecutionError()
            deadline = task["deadline"]
            if repo.clock() >= deadline:
                raise TimeoutError()
            try:
                actor = await self._long_request(deadline, self._long_actor, login_user, task)
                run_id = task["run_id"]
                state = task["remote_state"]
                if run_id is None:
                    observation = await self._long_request(deadline, provider.lookup_start, actor, ref, call_id)
                elif state not in {"SUCCEEDED", "FAILED", "CANCELLED"} and (
                    state != "WAITING_INPUT" or resuming_form is not None
                ):
                    observation = await self._long_request(deadline, provider.get_status, actor, ref, run_id)
                else:
                    observation = None
                if resuming_form is not None and observation is not None and observation.status == "WAITING_INPUT":
                    if observation.run_id != run_id or observation.ref != ref:
                        raise PlatformAgentOutputError()
                    form = observation.interaction
                    if form is None or (form.interaction_id, form.revision) != (
                        resuming_form.interaction_id,
                        resuming_form.revision,
                    ):
                        repo.close_long(dispatch, key, "FAILED", "UNSUPPORTED_INPUT")
                        raise PlatformAgentNonterminalError()
                    observation = None
                if observation is not None:
                    if wait_checkpoint is not None and observation.status == "WAITING_INPUT":
                        repo.save_long_wait(dispatch, key, observation, wait_checkpoint)
                        return None
                    repo.observe_long(dispatch.execution_id, key, dispatch=dispatch, observation=observation)
                    task = repo.long_snapshot(dispatch.execution_id, key)
                    if task["local_state"] in LOCAL_TERMINAL:
                        raise PlatformAgentExecutionError()
                    run_id, state = task["run_id"], task["remote_state"]
                if notify:
                    summary = self.long_summary(repo.get_execution(dispatch.execution_id), key)
                    if summary != previous_summary:
                        try:
                            notify(summary)
                        except Exception as exc:
                            logger.warning("平台 Agent 进度通知失败, error_type={}", type(exc).__name__)
                        previous_summary = summary
                if state == "WAITING_INPUT" and resuming_form is None:
                    repo.close_long(dispatch, key, "FAILED", "UNSUPPORTED_INPUT")
                    raise PlatformAgentNonterminalError()
                if state in {"FAILED", "CANCELLED"}:
                    repo.close_long(dispatch, key, "FAILED", f"REMOTE_{state}")
                    raise PlatformAgentUpstreamError()
                if state == "SUCCEEDED":
                    result = await self._long_request(deadline, provider.get_result, actor, ref, run_id)
                    if result is not None:
                        if (
                            result.agent_run_id != run_id
                            or result.ref != ref
                            or result.status != "SUCCEEDED"
                            or len(json.dumps(result.output, ensure_ascii=False).encode())
                            > self.config.max_payload_bytes
                        ):
                            raise PlatformAgentOutputError()
                        validate_value(result.output, schema, output=True)
                        actor = await self._long_request(deadline, self._long_actor, login_user, task)
                        await self._long_request(deadline, provider.check_use, actor, ref)
                        repo.ready_long_output(dispatch, key)
                        return deepcopy(result.output)
            except (TimeoutError, ConnectionError):
                if repo.clock() >= deadline:
                    raise TimeoutError() from None
            await self.long_pause(min(delay, max(0, deadline - repo.clock())))
            delay = min(1, delay * 2)

    def wake_long(self, tenant_id, execution_id, key=None):
        if self.long_wake:
            try:
                self.long_wake(tenant_id, execution_id, key)
            except Exception as exc:
                logger.warning("平台 Agent 补偿待扫描, error_type={}", type(exc).__name__)

    def notify_long(self, execution_id, key, notify):
        if notify:
            try:
                notify(self.long_summary(self.repository.get_execution(execution_id), key))
            except Exception as exc:
                logger.warning("平台 Agent 状态通知失败, error_type={}", type(exc).__name__)

    @staticmethod
    def long_summary(execution, key=None):
        calls = execution["calls"]
        tasks = {call_key: call["long_task"] for call_key, call in calls.items() if "long_task" in call}
        if not tasks or (key is not None and key not in tasks):
            return None
        # 旧 Mock 记录按启动时间排序。数据库 JSON 的键顺序不代表执行顺序。
        ordered = sorted(tasks, key=lambda k: (tasks[k].get("sequence", 0), tasks[k]["started"], k))
        selected = key if key is not None else ordered[-1]
        task = tasks[selected]
        summary = {
            name: task[name]
            for name in ("local_state", "remote_state", "cancel_state", "reason", "progress")
            if name in task
        }
        summary["execution_id"] = execution["execution_id"]
        summary["provider_mode"] = execution["provider_mode"]
        summary["call_sequence"] = ordered.index(selected) + 1
        if calls[selected].get("agent_run_id"):
            summary["agent_run_id"] = calls[selected]["agent_run_id"]
        if interaction := task.get("interaction"):
            summary["interaction_phase"] = interaction["phase"]
            summary["interaction_status_version"] = interaction["status_version"]
        if resume := task.get("resume"):
            summary.update(status_version=resume.get("status_version", 1), deadline=calls[selected]["deadline"])
        if (
            execution.get("state") == "WAITING"
            and task["local_state"] not in LOCAL_TERMINAL
            and task.get("interaction", {}).get("phase") == "WAITING_INPUT"
        ):
            summary["interaction_pending"] = True
        return summary

    async def reconcile_long(self, tenant_id, execution_id, key):
        if self.long_task_resume_available:
            await self._reconcile_long_task_resume(tenant_id, execution_id, key)
        await self._reconcile_long_cancel(tenant_id, execution_id, key)
        if self.config.mode == "mock" and self.enable_long_tasks and self.enable_interactions:
            await self._reconcile_interaction_receipt(tenant_id, execution_id, key)

    async def _reconcile_long_task_resume(self, tenant_id, execution_id, key):
        from bisheng.common.dependencies.user_deps import UserPayload

        repo = self.repository
        claim = repo.claim_long_task_resume_poll(execution_id, key, tenant_id)
        if claim is None:
            return
        lease, deadline = claim
        observation = result = error = None
        try:
            task = repo.long_snapshot(execution_id, key)
            user = UserPayload(user_id=task["user_id"], tenant_id=tenant_id, user_role=[])
            actor = await self._long_request(deadline, self._long_actor, user, task)
            ref = AgentReference.model_validate(task["ref"])
            provider = self.provider
            await self._long_request(deadline, provider.check_use, actor, ref)
            run_id = task["run_id"]
            # TODO [F126][EXT-01] 正式查回与同键重放的条件待确认。Mock 只查回原启动。
            if not run_id:
                observation = await self._long_request(
                    deadline, provider.lookup_start, actor, ref, f"{execution_id}:{key}"
                )
            # TODO [F126][EXT-02] 正式状态、结果、限流与保留期以双方契约为准。
            elif task["remote_state"] == "SUCCEEDED":
                reply = await self._long_request(deadline, provider.get_result, actor, ref, run_id)
                if reply is not None:
                    await self._validate_resume_result(deadline, execution_id, task, provider, actor, ref, reply)
                    actor = await self._long_request(deadline, self._long_actor, user, task)
                    await self._long_request(deadline, provider.check_use, actor, ref)
                    result = reply
            elif task["remote_state"] in {"QUEUED", "RUNNING"}:
                observation = await self._long_request(deadline, provider.get_status, actor, ref, run_id)
        except (
            UnAuthorizedError, TokenVersionMismatchError, PlatformAgentPermissionError, InvalidCatalogActionError,
            PermissionDeniedError,
        ):
            error = "FORBIDDEN"
        except (PlatformAgentOutputError, PlatformAgentVersionError, PlatformAgentConfigurationError):
            error = "INVALID_OUTPUT"
        except PlatformAgentEnvironmentError:
            error = "RUN_FAILED"
        except Exception as exc:
            logger.warning("平台 Agent 长任务查询待重试, error_type={}", type(exc).__name__)
        finally:
            repo.finish_long_task_resume_poll(execution_id, key, lease, observation=observation, result=result, error=error)

    async def _validate_resume_result(self, deadline, execution_id, task, provider, actor, ref, reply):
        if reply.agent_run_id != task["run_id"] or reply.ref != ref or reply.status != "SUCCEEDED":
            raise PlatformAgentOutputError()
        try:
            size = len(json.dumps(reply.output, ensure_ascii=False, allow_nan=False).encode())
        except (TypeError, ValueError):
            raise PlatformAgentOutputError() from None
        if size > self.config.max_payload_bytes:
            raise PlatformAgentOutputError()
        graph = self.repository.get_execution(execution_id)["graph_snapshot"]
        agent = task["resume"]["snapshot"]["agent_node"]
        binding = graph.get(PUBLICATION_KEY, {}).get("nodes", {}).get(agent, {})
        version = await self._long_request(deadline, provider.get_version, actor, ref)
        if (
            version.ref != ref
            or binding.get("schema_digest") != canonical_digest([version.input_schema, version.output_schema])
        ):
            raise PlatformAgentOutputError()
        validate_value(reply.output, version.output_schema, output=True)

    async def _reconcile_interaction_receipt(self, tenant_id, execution_id, key):
        from bisheng.common.dependencies.user_deps import UserPayload

        repo = self.repository
        claim = repo.claim_interaction_receipt_check(execution_id, key, tenant_id)
        if claim is None:
            return
        lease, deadline = claim
        receipt = None
        try:
            task = repo.long_snapshot(execution_id, key)
            interaction = task["interaction"]
            user = UserPayload(user_id=task["user_id"], tenant_id=tenant_id, user_role=[])
            actor = await self._long_request(deadline, self._long_actor, user, task)
            ref = AgentReference.model_validate(task["ref"])
            reference = interaction.get("remote_interaction")
            if reference is None:
                reference = {field: interaction["form"][field] for field in ("interaction_id", "revision")}
            receipt = await self._long_request(
                deadline,
                self.provider.lookup_submission,
                actor,
                ref,
                task["run_id"],
                AgentInteractionReference.model_validate(reference),
                interaction["remote_key"],
            )
        except Exception as exc:
            logger.warning("平台 Agent 回执核对待重试, error_type={}", type(exc).__name__)
        finally:
            repo.finish_interaction_receipt_check(execution_id, key, lease, receipt)

    async def _reconcile_long_cancel(self, tenant_id, execution_id, key):
        from bisheng.common.dependencies.user_deps import UserPayload

        repo = self.repository
        lease = repo.claim_long_reconcile(execution_id, key, tenant_id)
        if lease is None:
            return
        outcome = None
        try:
            task = repo.long_snapshot(execution_id, key)
            deadline = task["lease_until"]
            user = UserPayload(user_id=task["user_id"], tenant_id=tenant_id, user_role=[])
            actor = await self._long_request(deadline, self._long_actor, user, task)
            provider = self.provider
            ref = AgentReference.model_validate(task["ref"])
            if task["remote_state"] in REMOTE_TERMINAL:
                return
            if task.get("resume"):
                await self._long_request(deadline, provider.check_use, actor, ref)
            if task["run_id"]:
                observation = await self._long_request(deadline, provider.get_status, actor, ref, task["run_id"])
            else:
                observation = await self._long_request(
                    deadline, provider.lookup_start, actor, ref, f"{execution_id}:{key}"
                )
            if observation is None:
                return
            repo.observe_long(execution_id, key, lease=lease, observation=observation)
            if not repo.permit_long_cancel(execution_id, key, lease):
                return
            actor = await self._long_request(deadline, self._long_actor, user, task)
            if task.get("resume"):
                await self._long_request(deadline, provider.check_use, actor, ref)
            # TODO [F126][EXT-03] 正式取消受理、拒绝和终态核对以双方契约为准。
            reply = await self._long_request(
                deadline, provider.cancel, actor, ref, observation.run_id, f"{execution_id}:{key}:cancel"
            )
            if reply in {"ACCEPTED", "REJECTED"}:
                outcome = reply
        except (
            UnAuthorizedError,
            TokenVersionMismatchError,
            PlatformAgentPermissionError,
            PlatformAgentEnvironmentError,
            InvalidCatalogActionError,
            PermissionDeniedError,
        ):
            outcome = "UNCONFIRMED"
        except PlatformAgentExecutionError:
            outcome = "UNCONFIRMED"
        except Exception as exc:
            logger.warning("平台 Agent 补偿稍后重试, error_type={}", type(exc).__name__)
        finally:
            repo.finish_long_reconcile(execution_id, key, lease, outcome)
