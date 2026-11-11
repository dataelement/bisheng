"""Transport-neutral workflow admission injected by the owning endpoint.

The bound implementation carries the trusted connection resource and original
identity. Client supplied mode, version and resource IDs are only claims.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class WorkflowExecutionPort(Protocol):
    async def prepare_initial(
        self,
        *,
        claimed_flow_id: str | None,
        graph: dict | None,
        chat_id: str | None,
        execution_mode: str | None = None,
        version_hint: int | str | None = None,
    ) -> dict: ...
