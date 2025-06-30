from enum import Enum

# 工具 执行历史记录的buffer大小，token来计算
DefaultToolBuffer = 20000


class TaskStatus(Enum):
    WAITING = 'waiting'  # 待执行
    PROCESSING = 'processing'  # 执行中
    INPUT = 'input'  # 等待用户输入
    SUCCESS = 'success'  # 任务成功
    FAILED = 'failed'  # 任务失败
