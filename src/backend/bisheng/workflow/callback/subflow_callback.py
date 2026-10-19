import time
from collections.abc import Callable

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.event import NodeEndData, NodeStartData


def _never_stop() -> bool:
    return False


def _no_op() -> None:
    return None


class SubflowCallback(BaseCallback):
    """F086: callback of a workflow that runs inside a subflow node.

    Chat events (stream, output, guide word, user input) are dropped through
    the inherited no-op methods, so nothing of the subflow reaches the
    conversation. Node runs are recorded in execution order for the parent's
    run log and for picking the End node results.

    The parent's stop flag is only checked when the parent callback sends an
    event; since this callback swallows every event, it checks the flag itself
    at each inner node start and end.
    """

    def __init__(
        self,
        stop_check: Callable[[], bool] | None = None,
        on_stop: Callable[[], None] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._stop_check = stop_check or _never_stop
        self._on_stop = on_stop or _no_op
        self._start_times: dict[str, float] = {}
        self.node_logs: list[dict] = []

    def _check_stop(self) -> None:
        if self._stop_check():
            self._on_stop()

    def on_node_start(self, data: NodeStartData):
        self._start_times[data.unique_id] = time.monotonic()
        self._check_stop()

    def on_node_end(self, data: NodeEndData):
        started = self._start_times.pop(data.unique_id, None)
        duration_ms = int((time.monotonic() - started) * 1000) if started is not None else 0
        self.node_logs.append(
            {
                "node_id": data.node_id,
                "name": data.name,
                "duration_ms": duration_ms,
                "reason": data.reason,
                "log_data": data.log_data,
                "input_data": data.input_data,
            }
        )
        self._check_stop()

    @property
    def executed_node_ids(self) -> list[str]:
        return [one["node_id"] for one in self.node_logs]

    def _last_failed(self) -> dict | None:
        for one in reversed(self.node_logs):
            if one["reason"]:
                return one
        return None

    def last_failed_node_name(self) -> str:
        failed = self._last_failed()
        return failed["name"] if failed else ""

    def last_failed_reason(self) -> str:
        failed = self._last_failed()
        return failed["reason"] if failed else ""
