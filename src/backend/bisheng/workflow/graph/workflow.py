import json
import time
from typing import Dict

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.graph.graph_engine import GraphEngine


class Workflow:

    def __init__(self,
                 workflow_id: str,
                 user_id: str = None,
                 workflow_data: Dict = None,
                 async_mode: bool = False,
                 max_steps: int = 0,
                 timeout: int = 0,
                 callback: BaseCallback = None):

        # 运行的唯一标识，保存到数据库的唯一ID
        self.workflow_id = workflow_id
        self.user_id = user_id

        # 超时时间，多久没有接收到用户输入终止workflow运行（单位：分钟）
        self.timeout = timeout
        self.current_time = None

        self.graph_engine = GraphEngine(user_id=user_id,
                                        async_mode=async_mode,
                                        workflow_id=workflow_id,
                                        workflow_data=workflow_data,
                                        max_steps=max_steps,
                                        callback=callback)

    def run(self, input_data: dict = None) -> (str, str):
        """
        params:
            input_data: user input data 不为空则执行continue
        return: workflow_status, reason
        """
        # 执行workflow
        if input_data is not None:
            user_input_str = ' '.join([json.dumps(msg, ensure_ascii=False) for _, msg in input_data.items()])
            self.graph_engine.graph_state.save_context(content=user_input_str, msg_sender='human')
            self.graph_engine.continue_run(input_data)
        else:
            # 首次运行时间
            self.current_time = time.time()
            self.graph_engine.run()
        while self.graph_engine.status == WorkflowStatus.RUNNING.value:
            self.graph_engine.continue_run()
        return self.graph_engine.status, self.graph_engine.reason

    async def arun(self, input_data: dict = None) -> (str, str):
        """
        params:
            input_data: user input data 不为空则执行continue
        return: workflow_status, reason
        """
        # 执行workflow
        if input_data is not None:
            user_input_str = ' '.join([json.dumps(msg, ensure_ascii=False) for _, msg in input_data.items()])
            self.graph_engine.graph_state.save_context(content=user_input_str, msg_sender='human')
            await self.graph_engine.acontinue_run(input_data)
        else:
            # 首次运行时间
            self.current_time = time.time()
            await self.graph_engine.arun()
        while self.graph_engine.status == WorkflowStatus.RUNNING.value:
            await self.graph_engine.acontinue_run()
        return self.graph_engine.status, self.graph_engine.reason
