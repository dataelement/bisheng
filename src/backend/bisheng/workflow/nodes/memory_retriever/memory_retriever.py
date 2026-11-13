"""Workflow ``memory_retriever`` node (F132 design §4.2, AC-78–AC-86).

Reads the run's ``chat_id`` and the ONLINE version's memory switch from the two
read-only ``graph_state`` fields (filled by the Celery task, R5), resolves
enablement through ``MemoryGate`` and searches the current user's memory. It
never writes memory and never writes turn records; the run log carries only the
query and the number of returned items.
"""

from __future__ import annotations

import json
from typing import Any

from bisheng.common.errcode.memory import MemorySearchLimitInvalidError, MemoryWorkflowSwitchOffError
from bisheng.workflow.common.node import NodeType
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser

DEFAULT_LIMIT = 20
MIN_LIMIT = 1
MAX_LIMIT = 100
OUTPUT_KEY = "retrieved_memory"
SEARCH_TIMEOUT_SECONDS = 60


def parse_limit(value: Any) -> int:
    """``limit`` must be an integer from 1 to 100; missing means 20 (AC-80)."""
    if value is None:
        return DEFAULT_LIMIT
    number = None
    if isinstance(value, bool):
        number = None
    elif isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        number = int(value.strip())
    if number is None or not MIN_LIMIT <= number <= MAX_LIMIT:
        raise MemorySearchLimitInvalidError()
    return number


def _node_limit(node: dict) -> Any:
    for group in (node.get("data") or {}).get("group_params") or []:
        for param in group.get("params") or []:
            if param.get("key") == "limit":
                return param.get("value")
    return None


def check_memory_nodes_for_publish(graph_data: dict | None) -> None:
    """Publish check (AC-85, AC-80): a graph with retriever nodes needs the start
    node switch on, and every retriever node needs a valid ``limit``."""
    from bisheng.memory.domain.services.app_switch import start_node_memory_enabled

    retrievers = [
        n
        for n in (graph_data or {}).get("nodes") or []
        if (n.get("data") or {}).get("type") == NodeType.MEMORY_RETRIEVER.value
    ]
    if not retrievers:
        return
    if not start_node_memory_enabled(graph_data):
        raise MemoryWorkflowSwitchOffError()
    for node in retrievers:
        parse_limit(_node_limit(node))


def _to_text(value: Any) -> str:
    """Referenced values that are not text become text (AC-79)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


class MemoryRetrieverNode(BaseNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.limit = parse_limit(self.node_params.get("limit"))
        self._query = ""
        self._count = 0

    def _resolve_query(self) -> str:
        template = PromptTemplateParser(template=_to_text(self.node_params.get("query")))
        values = {key: _to_text(self.get_other_node_variable(key)) for key in template.extract()}
        return template.format(values).strip()

    def _run(self, unique_id: str) -> dict[str, Any]:
        self._query = self._resolve_query()
        self._count = 0
        items: list[dict] = []
        if self._query:
            items = self._search(self._query)
        self._count = len(items)
        return {OUTPUT_KEY: items}

    def _search(self, query: str) -> list[dict]:
        from bisheng.memory.domain.ports import SCENE_WORKFLOW
        from bisheng.memory.domain.services.gate import MemoryGate
        from bisheng.memory.domain.services.workflow_retrieval import retrieve_for_workflow
        from bisheng.utils.async_utils import run_async_safe

        ctx = MemoryGate.resolve_sync(
            self.graph_state.chat_id,
            SCENE_WORKFLOW,
            app_enabled=self.graph_state.memory_enabled,
            app_id=self.workflow_id,
            app_name=self.workflow_name,
            actor_user_id=self.user_id,
        )
        if ctx is None:
            # not registered, user switched memory off, or the workflow switch is off (AC-83)
            return []
        # MemorySearchUnavailableError propagates: the node fails with a reason (AC-84)
        return run_async_safe(retrieve_for_workflow(ctx, query, self.limit), timeout=SEARCH_TIMEOUT_SECONDS)

    def parse_log(self, unique_id: str, result: dict) -> Any:
        # query and count only, never item text (AC-86)
        return [
            [
                {"key": f"{self.id}.query", "value": self._query, "type": "params"},
                {"key": f"{self.id}.retrieved_count", "value": self._count, "type": "params"},
            ]
        ]
