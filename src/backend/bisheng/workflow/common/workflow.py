from enum import Enum


class WorkflowStatus(Enum):
    WAITING = 'WAITING'  # 等待异步任务调度
    RUNNING = 'RUNNING'
    SUCCESS = 'SUCCESS'
    FAILED = 'FAILED'
    INPUT = 'INPUT'  # 待输入状态
    INPUT_OVER = 'INPUT_OVER'  # 已输入状态
