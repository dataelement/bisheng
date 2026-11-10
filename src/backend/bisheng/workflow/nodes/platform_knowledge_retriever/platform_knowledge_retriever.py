"""昆联检索节点复用 Workflow 变量池和结果提交钩子。"""

import asyncio
import time
from contextlib import contextmanager

from bisheng.common.errcode.flow import PlatformKnowledgeExecutionError
from bisheng.utils.async_utils import run_async_safe
from bisheng.workflow.domain.schemas.platform_knowledge import MISSING
from bisheng.workflow.nodes.base import BaseNode


class PlatformKnowledgeRetrieverNode(BaseNode):
    def lookup(self, path):
        node_id, key = path.split(".", 1)
        base, _, field = key.partition("#")
        value = self.graph_state.variables_pool.get(node_id, {}).get(base, MISSING)
        if not field:
            return value
        if isinstance(value, dict):
            return value.get(field, MISSING)
        if isinstance(value, list) and field.isdecimal() and int(field) < len(value):
            return value[int(field)]
        return MISSING

    def _run(self, unique_id):
        self.graph_state.variables_pool.pop(self.id, None)
        run = self.platform_knowledge_context
        if not run:
            raise PlatformKnowledgeExecutionError()
        self.deadline = time.monotonic() + run.service.config.retrieve_timeout_seconds
        return run_async_safe(
            run.invoke(self.node_data.model_dump(), self.lookup, unique_id, self.deadline), timeout=None
        )

    @contextmanager
    def output_commit_scope(self):
        try:
            yield
            run_async_safe(
                self.platform_knowledge_context.commit(self.id, self.current_step, self.deadline), timeout=None
            )
        except BaseException:
            self.graph_state.variables_pool.pop(self.id, None)
            raise

    def diagnostics(self):
        run = self.platform_knowledge_context
        if not run:
            return []
        return [
            {"key": key, "value": value, "type": "params"}
            for key, value in {
                "provider_mode": run.service.config.mode,
                "resource_id": (self.node_params.get("knowledge") or {}).get("resource_id"),
                "execution_id": run.execution_id,
                "call_id": self.exec_unique_id,
            }.items()
        ]

    def parse_log(self, unique_id, result):
        return [
            [
                *self.diagnostics(),
                *({"key": f"{self.id}.{key}", "value": value, "type": "variable"} for key, value in result.items()),
            ]
        ]

    def failure_log(self):
        return [self.diagnostics()]

    async def arun(self, state):
        return await asyncio.to_thread(self.run, state)
