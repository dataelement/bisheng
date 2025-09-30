import hashlib
from enum import Enum
from typing import Optional, Any

from pydantic import BaseModel, Field


class PromptManage(BaseModel):
    prompt_dict: dict = Field(default_factory=dict, description='存储prompt映射到任务步骤的信息')

    def insert_prompt(self, prompt: str, step_type: str, step_info: Any):
        md5_str = hashlib.md5(prompt.encode()).hexdigest()
        self.prompt_dict[md5_str] = {
            "step_type": step_type,
            "step_info": step_info,
            "prompt": prompt
        }

    def get_prompt_info(self, prompt: str) -> Optional[dict]:
        md5_str = hashlib.md5(prompt.encode()).hexdigest()
        return self.prompt_dict.get(md5_str, None)


class ExecConfig(BaseModel):
    debug: bool = Field(default=False, description="是否是调试模式。开启后会记录llm的输入和输出")
    debug_id: Optional[str] = Field(default=None, description="调试记录唯一ID, 用来写唯一的文件")
    tool_buffer: int = Field(default=50000, description='工具执行历史记录的最大token，超过后需要总结下历史记录')
    max_steps: int = Field(default=200, description='单个任务最大执行步骤数，防止死循环')
    retry_num: int = Field(default=3, description='灵思任务执行过程中模型调用重试次数')
    retry_sleep: int = Field(default=5, description='灵思任务执行过程中模型调用重试间隔时间（秒）')
    max_file_num: int = Field(default=5, description='生成SOP时，prompt里放的用户上传文件信息的数量')
    retry_temperature: float = Field(default=1, description='重试时的模型温度')
    file_content_length: int = Field(default=5000, description='拆分子任务时读取文件内容的字符数，超过后会截断')
    prompt_manage: PromptManage = Field(default_factory=PromptManage,
                                        description='Prompt管理器, 负责管理任务执行过程中的Prompt')


CallUserInputToolName = "call_user_input"


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
