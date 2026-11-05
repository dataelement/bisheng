"""Bounded, content-free diagnostics shared by knowledge read paths."""

from collections.abc import Callable
from time import perf_counter

from bisheng.common.services.metric_log import emit_metric
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.logger import trace_id_var


def knowledge_list_source(request, *, operation: str, file_type: int | None = None) -> str:
    hint = getattr(request, "headers", {}).get("x-knowledge-list-source")
    if hint in {"file_list", "folder_tree", "search"}:
        return hint
    if operation == "search":
        return "search"
    return "folders_only" if file_type == 0 else "children"


class KnowledgeReadTrace:
    """Record fixed stages without extra queries, tasks or exception contents."""

    def __init__(self, operation: str, *, clock: Callable[[], float] = perf_counter, **fields):
        self.clock = clock
        self.started_at = clock()
        self.stage_started_at = self.started_at
        self.current_stage: str | None = None
        self.fields = {
            "trace_id": trace_id_var.get(),
            "tenant_id": get_current_tenant_id(),
            "operation": operation,
            **fields,
        }
        self.durations: dict[str, float] = {}

    def _emit(self, event: str, **fields) -> None:
        emit_metric(
            "knowledge_read_trace",
            **self.fields,
            **self.durations,
            event=event,
            stage=self.current_stage,
            total_elapsed_ms=(self.clock() - self.started_at) * 1000,
            **fields,
        )

    def __enter__(self):
        self._emit("start")
        return self

    def _close_stage(self, now: float) -> None:
        if self.current_stage:
            key = f"{self.current_stage}_elapsed_ms"
            self.durations[key] = self.durations.get(key, 0) + (now - self.stage_started_at) * 1000
        self.stage_started_at = now

    def stage(self, name: str) -> None:
        self._close_stage(self.clock())
        self.current_stage = name
        self._emit("stage_start")

    def update(self, **fields) -> None:
        self.fields.update(fields)

    def __exit__(self, error_type, _error, _traceback):
        self._close_stage(self.clock())
        self._emit(
            "end", status="error" if error_type else "success", error_type=error_type.__name__ if error_type else None
        )
