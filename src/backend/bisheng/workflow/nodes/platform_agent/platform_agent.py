"""固定版本的平台 Agent 同步节点。构造时不查询资源或发送请求。"""

import asyncio
from contextlib import contextmanager
from copy import deepcopy

from bisheng.common.errcode.flow import PlatformAgentExecutionError, PlatformAgentUnknownError
from bisheng.utils.async_utils import run_async_safe
from bisheng.workflow.domain.schemas.platform_agent import MISSING, node_configuration
from bisheng.workflow.nodes.base import BaseNode


class PlatformAgentNode(BaseNode):
    def __init__(self, *args, **kwargs):
        self.platform_agent_context = kwargs.get("platform_agent_context")
        super().__init__(*args, **kwargs)

    def lookup(self, path):
        if not isinstance(path, str) or "." not in path:
            return MISSING
        node_id, key = path.split(".", 1)
        field = None
        if "#" in key:
            key, field = key.split("#", 1)
        value = self.graph_state.variables_pool.get(node_id, {}).get(key, MISSING)
        if field is None or value is MISSING:
            return value
        if isinstance(value, dict):
            return value.get(field, MISSING)
        if isinstance(value, list) and field.isdigit() and int(field) < len(value):
            return value[int(field)]
        return MISSING

    def _run(self, unique_id):
        context = self.platform_agent_context
        if context is None:
            raise PlatformAgentExecutionError()
        # 由领域控制完整调用预算。节点导入不触发 Worker 的任务注册。
        node = self.node_data.model_dump()
        args = (context["login_user"], self.workflow_id, context["dispatch"], node, self.current_step, self.lookup)
        service = context["service"]
        configuration = node_configuration(node)
        if "long_task_resume_key" in context:
            if (
                configuration.execution_mode != "async" or configuration.allow_interaction
                or context["long_task_resume_key"] != f"{self.id}:{self.current_step}"
                or "long_task_resume_result" not in context
            ):
                raise PlatformAgentExecutionError()
            return {"result": context.pop("long_task_resume_result")}
        if configuration.allow_interaction and "interaction_result" in context:
            return {"result": context.pop("interaction_result")}
        if configuration.execution_mode == "async":
            notify = getattr(self.callback_manager, "on_agent_long_task", None)
            execution = service.invoke_long_node(*args, notify=notify)
        else:
            execution = service.invoke_node(*args)
        result = run_async_safe(execution, timeout=None)
        return {"result": result}

    @contextmanager
    def output_commit_scope(self):
        context = self.platform_agent_context
        if not context:
            raise PlatformAgentExecutionError()
        if "long_task_resume_key" in context:
            # 4D 的图变量仅供本次恢复使用。持久消息和终态由外层事务一起提交。
            yield
            return
        existed = self.id in self.graph_state.variables_pool
        original = deepcopy(self.graph_state.variables_pool.get(self.id))
        try:
            with context["service"].repository.output_scope(
                context["dispatch"], self.id, self.current_step, context["service"].current_config
            ):
                yield
        except BaseException as error:
            if existed:
                self.graph_state.variables_pool[self.id] = original
            else:
                self.graph_state.variables_pool.pop(self.id, None)
            if isinstance(error, PlatformAgentUnknownError) and self.node_params.get("execution_mode") == "async":
                context["service"].notify_long(
                    context["dispatch"].execution_id,
                    f"{self.id}:{self.current_step}",
                    getattr(self.callback_manager, "on_agent_long_task", None),
                )
            raise
        if self.node_params.get("execution_mode") == "async":
            context["service"].notify_long(
                context["dispatch"].execution_id,
                f"{self.id}:{self.current_step}",
                getattr(self.callback_manager, "on_agent_long_task", None),
            )

    def parse_log(self, unique_id, result):
        return [[*self.diagnostic_log(), {"key": "result", "value": result["result"], "type": "variable"}]]

    def diagnostic_log(self):
        context = self.platform_agent_context
        if not context:
            return []
        items = [
            {"key": "provider_mode", "value": context["service"].config.mode, "type": "params"},
            {"key": "agent_ref", "value": self.node_params.get("agent_ref"), "type": "params"},
            {"key": "execution_id", "value": context["dispatch"].execution_id, "type": "params"},
        ]
        try:
            calls = context["service"].repository.get_execution(context["dispatch"].execution_id)["calls"]
            call = calls.get(f"{self.id}:{self.current_step}", {})
            if call.get("agent_run_id"):
                items.append({"key": "agent_run_id", "value": call["agent_run_id"], "type": "params"})
        except PlatformAgentExecutionError:
            pass
        return items

    def failure_log(self):
        return [self.diagnostic_log()]

    async def arun(self, state):
        return await asyncio.to_thread(self.run, state)
