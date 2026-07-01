import json
import time

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.graph.graph_engine import GraphEngine


class Workflow:
    def __init__(
        self,
        workflow_id: str,
        workflow_name: str = "",
        user_id: int = None,
        workflow_data: dict = None,
        async_mode: bool = False,
        max_steps: int = 0,
        timeout: int = 0,
        callback: BaseCallback = None,
        tenant_id: int = None,
        flow_user_id: int = None,
    ):

        # Unique identifier of the run, unique saved to the databaseID
        self.workflow_id = workflow_id
        self.user_id = user_id
        # Owner tenant of the Flow — threaded from FlowDao at task entry so
        # downstream nodes can call LLMService.get_*_llm(tenant_id=...) for
        # the F022 system-config row owned by the Flow's tenant (INV-T18).
        # ``None`` falls back to ContextVar / Root inside _resolve_tenant_id.
        self.tenant_id = tenant_id
        # Flow creator (config author) — threaded from FlowDao at task entry.
        # F041: knowledge-space retrieval with the permission toggle OFF filters
        # by the config author's view_file, so nodes need the creator id distinct
        # from ``user_id`` (the runtime user who triggered the run).
        self.flow_user_id = flow_user_id

        # Timeout, how long has the user input not been received terminatedworkflowRun (in minutes)
        self.timeout = timeout
        self.current_time = None

        self.graph_engine = GraphEngine(
            user_id=user_id,
            async_mode=async_mode,
            workflow_id=workflow_id,
            workflow_name=workflow_name or workflow_id,
            workflow_data=workflow_data,
            max_steps=max_steps,
            callback=callback,
            tenant_id=tenant_id,
            flow_user_id=flow_user_id,
        )

    def save_user_input_history(self, input_data: dict | None):
        if not input_data:
            return
        user_input_str = ""
        for _, msg in input_data.items():
            # Under the special handling of session input,keyRemove
            if len(msg) == 1 and "user_input" in msg:
                user_input_str += msg["user_input"]
                continue
            user_input_str += "\n" + json.dumps(msg, ensure_ascii=False)
        self.graph_engine.graph_state.save_context(content=user_input_str, msg_sender="human")

    def run(self, input_data: dict = None) -> (str, str):
        """
        params:
            input_data: user input data If not empty, executecontinue
        return: workflow_status, reason
        """
        # Implementationworkflow
        if input_data is not None:
            self.graph_engine.continue_run(input_data)
        else:
            # First run time
            self.current_time = time.time()
            self.graph_engine.run()
        while self.graph_engine.status == WorkflowStatus.RUNNING.value:
            self.graph_engine.continue_run()
        return self.graph_engine.status, self.graph_engine.reason

    async def arun(self, input_data: dict = None) -> (str, str):
        """
        params:
            input_data: user input data If not empty, executecontinue
        return: workflow_status, reason
        """
        # Implementationworkflow
        if input_data is not None:
            await self.graph_engine.acontinue_run(input_data)
        else:
            # First run time
            self.current_time = time.time()
            await self.graph_engine.arun()
        while self.graph_engine.status == WorkflowStatus.RUNNING.value:
            await self.graph_engine.acontinue_run()
        return self.graph_engine.status, self.graph_engine.reason

    def stop(self):
        self.graph_engine.stop()

    def status(self):
        return self.graph_engine.status

    def reason(self):
        return self.graph_engine.reason
