from enum import Enum

CallUserInputToolName = "call_user_input"


class TaskStatus(Enum):
    WAITING = "waiting"  # 待执行
    PROCESSING = "processing"  # 执行中
    INPUT = "input"  # 等待用户输入
    INPUT_OVER = "input_over"  # 用户输入已完成
    SUCCESS = "success"  # 任务成功
    FAILED = "failed"  # 任务失败


# 任务执行模式
class TaskMode(str, Enum):
    REACT = "react"  # React 模式
    FUNCTION = "func_call"  # func call 模式
