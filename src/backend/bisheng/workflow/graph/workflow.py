from queue import Queue, Empty
from typing import Dict

from loguru import logger

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.graph.graph_engine import GraphEngine


class Workflow:

    def __init__(self, user_id: str = None, workflow_data: Dict = None,
                 max_steps: int = 0, timeout: int = 0, callback: BaseCallback = None,
                 input_queue: Queue = None):
        self.user_id = user_id

        # 超时时间，多久没有接收到用户输入终止workflow运行（单位：分钟）
        self.timeout = timeout

        self.graph_engine = GraphEngine(user_id=user_id, workflow_data=workflow_data,
                                        max_steps=max_steps, callback=callback)
        self.graph_status = WorkflowStatus.RUNNING.value
        self.graph_reason = ""

        self.first_run = True
        # todo 定义个queue基类，支持不同实现的queue
        self.input_queue = input_queue

    def run(self) -> (str, str):
        """
        return: workflow_status, reason
        """
        while True:
            if self.first_run:
                self.first_run = False
                self.graph_engine.run()
                continue
            # 判断graph的状态
            if self.graph_engine.status in [WorkflowStatus.SUCCESS.value, WorkflowStatus.FAILED.value]:
                self.graph_status = self.graph_engine.status
                self.graph_reason = self.graph_engine.reason
                break
            elif self.graph_engine.status == WorkflowStatus.INPUT.value:
                # 等待用户输入
                try:
                    input_data = self.input_queue.get(block=True, timeout=self.timeout * 60)
                    self.graph_engine.continue_run(data=input_data)
                except Empty:
                    self.graph_status = WorkflowStatus.FAILED.value
                    self.graph_reason = "user input timeout"
                    break
                except Exception as e:
                    self.graph_status = WorkflowStatus.FAILED.value
                    self.graph_reason = str(e)
                    break
            else:  # 不应该出现的情况
                logger.warning("graph status error: %s", self.graph_engine.status)
                self.graph_engine.continue_run(None)

        return self.graph_status, self.graph_reason

