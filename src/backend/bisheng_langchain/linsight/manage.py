from langchain_core.language_models import BaseLanguageModel
from langchain_core.tools import BaseTool
from pydantic import Field, BaseModel, model_validator

from bisheng_langchain.linsight.const import TaskStatus
from bisheng_langchain.linsight.task import Task


class TaskManage(BaseModel):
    """
    Task manager for handling tasks and workflows.
    This class is responsible for managing the lifecycle of tasks,
    including creation, execution, and monitoring.
    """

    file_dir: str = Field(default="", description='Directory for storing files')
    llm: BaseLanguageModel = Field(..., description='Language model to use for processing queries')
    finally_sop: str = Field(default="", description="Final SOP to be used in the agent's processing.")

    tasks: list[dict | Task] = Field(default_factory=list, description='List of tasks managed by the task manager')
    task_step_map: dict[str, Task] = Field(default_factory=dict, description='Map of step ID to Task instances')
    tools: list[BaseTool] = Field(default_factory=list, description='List of tools managed by the tool manager')
    tool_map: dict[str, BaseTool] = Field(default_factory=dict, description='Map of tool names to tool instances')

    @model_validator(mode="after")
    def validate_tasks(self) -> "TaskManage":

        res = []
        for task in self.tasks:
            if isinstance(task, dict):
                res.append(Task(**task,
                                task_manager=self, llm=self.llm, file_dir=self.file_dir,
                                finally_sop=self.finally_sop))
            elif isinstance(task, Task):
                task.task_manager = self
                task.llm = self.llm
                task.file_dir = self.file_dir
                task.finally_sop = self.finally_sop
                res.append(task)
            else:
                raise ValueError(f"Invalid task type: {type(task)}. Expected dict or Task instance.")
            res.append(Task(**task))
        self.tasks = res
        self.task_step_map = {task.step_id: task for task in self.tasks}
        self.tool_map = {tool.name: tool for tool in self.tools}
        return self

    def get_all_tool_schema(self) -> list[dict]:
        """
        Retrieve all tools managed by the tool manager.
        :return: List of tools input schema.
        """
        # 所有tool的schema里增加一个`_call_reason`的必填字段，让模型总结下为啥需要使用这个工具
        res = []
        for one in self.tools:
            schema = one.args()
            res.append(schema)
        return res

    async def ainvoke_tool(self, name: str, params: dict) -> str:
        """
        Add a new tool to the tool manager.
        :param name: The name of the tool to be executed.
        :param params: The params of the tool to be invoked.
        """
        if name not in self.tool_map:
            return f"tool {name} exec error, because tool name is not found"
        try:
            res = await self.tool_map[name].ainvoke(**params)
            if not isinstance(res, str):
                res = str(res)
            return res
        except Exception as e:
            return f"tool {name} exec error, something went wrong: {str(e)[:20]}"

    def get_step_answer(self, step_id: str) -> str:
        if step_id not in self.task_step_map:
            return ""
        return self.task_step_map[step_id].answer

    async def get_processed_steps(self):
        """Get the steps that have been processed."""
        success_steps = []
        for task in self.tasks:
            if task.status == TaskStatus.SUCCESS.value:
                success_steps.append(task.step_id)
        return ','.join(success_steps)

    async def get_workflow(self):
        res = []
        for task in self.tasks:
            res.append({
                'step_id': task.step_id,
                'target': task.target,
                'description': task.status
            })
        return res
