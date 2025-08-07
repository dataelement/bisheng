from typing import Optional, Any

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    task_id: str = Field(..., description='触发事件的任务ID')


# 任务步骤执行事件
class ExecStep(BaseEvent):
    call_id: str = Field(..., description='执行步骤的唯一标识符')
    call_reason: str = Field(..., description='执行步骤的原因')
    name: str = Field(..., description='执行步骤的名称')
    # params: str = Field(..., description='执行步骤的参数')
    params: Optional[Any] = Field(default=None, description='执行步骤的参数')
    output: Optional[str] = Field(default=None, description='工具执行的结果')
    step_type: Optional[str] = Field(default="tool_call",
                                     description='步骤类型。tool_call: 工具调用；react_step: 固定步骤或回答;')
    status: str = Field(..., description='执行状态，start: 开始执行；end：执行结束')
    # 额外信息
    extra_info: Optional[dict] = Field(default={}, description='额外信息，包含文件上传等其他信息')


# 生成子任务的事件
class GenerateSubTask(BaseEvent):
    subtask: list[dict] = Field(..., description='生成的子任务信息列表')


# 需要用户输入的事件
class NeedUserInput(BaseEvent):
    call_reason: str = Field(..., description='需要用户输入的原因')


class TaskStart(BaseEvent):
    name: str = Field(..., description='任务名称')


class TaskEnd(BaseEvent):
    name: str = Field(..., description='任务名称')
    status: str = Field(..., description='任务状态')
    answer: str = Field(..., description='任务最终结果')
    data: Any = Field(..., description='任务数据')
