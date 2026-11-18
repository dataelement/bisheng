"""A WS execution Port bound to the trusted endpoint resource and identity."""

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.workflow.application.execution_admission import prepare_initial


class BoundWorkflowExecutionPort:
    def __init__(self, workflow_id: str, identity, *, allow_preview: bool = True):
        self._workflow_id = str(workflow_id)
        self._identity = identity
        self._allow_preview = allow_preview

    async def prepare_initial(self, *, claimed_flow_id, graph, chat_id, execution_mode=None, version_hint=None) -> dict:
        if claimed_flow_id is None or str(claimed_flow_id) != self._workflow_id:
            raise ResourceReferenceInvalidError(reason="workflow_connection_root_mismatch")
        # Existing channel ONLINE/session checks remain in the actual client.
        prepared = await prepare_initial(
            self._identity,
            self._workflow_id,
            graph,
            execution_mode=execution_mode,
            version_hint=version_hint,
            allow_preview=self._allow_preview,
        )
        return prepared.graph
