from enum import Enum

# 工具 执行历史记录的buffer大小，token来计算
DefaultToolBuffer = 20000
# 单个任务最大执行步骤数，防止死循环
MaxSteps = 50


class TaskStatus(Enum):
    WAITING = 'waiting'  # 待执行
    PROCESSING = 'processing'  # 执行中
    INPUT = 'input'  # 等待用户输入
    INPUT_OVER = 'input_over'  # 用户输入已完成
    SUCCESS = 'success'  # 任务成功
    FAILED = 'failed'  # 任务失败


# 任务执行模式
class TaskMode(str, Enum):
    REACT = 'react'  # React 模式
    FUNCTION = 'func_call'  # func call 模式
