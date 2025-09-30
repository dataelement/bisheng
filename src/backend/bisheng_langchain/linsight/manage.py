import asyncio
import json
import time
import traceback
from asyncio.queues import Queue
from functools import cached_property
from typing import Optional, AsyncIterator

from langchain_core.language_models import BaseLanguageModel
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field, BaseModel, model_validator, ConfigDict

from bisheng_langchain.linsight.const import TaskStatus, TaskMode, CallUserInputToolName, ExecConfig
from bisheng_langchain.linsight.event import BaseEvent
from bisheng_langchain.linsight.react_task import ReactTask
from bisheng_langchain.linsight.task import Task
from bisheng_langchain.linsight.utils import generate_uuid_str


class TaskManage(BaseModel):
    """
    Task manager for handling tasks and workflows.
    This class is responsible for managing the lifecycle of tasks,
    including creation, execution, and monitoring.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    tasks: list[dict | Task] = Field(default_factory=list,
                                     description='List of tasks managed by the task manager, not include sub task')
    task_map: dict[str, Task] = Field(default_factory=dict, description='Map of task IDs to Task instances')
    task_step_map: dict[str, Task] = Field(default_factory=dict, description='Map of step ID to Task instances')
    tools: list[BaseTool] = Field(default_factory=list, description='List of tools managed by the tool manager')
    tool_map: dict[str, BaseTool] = Field(default_factory=dict, description='Map of tool names to tool instances')
    aqueue: Optional[Queue] = Field(default=None, description='Asynchronous queue for task processing')
    task_mode: str = Field(default=TaskMode.FUNCTION.value,
                           description='Mode of the task execution, can be FUNCTION or REACT')

    @model_validator(mode="after")
    def validate_tasks(self) -> "TaskManage":
        self.aqueue = Queue(maxsize=50)
        self.tool_map = {tool.name: tool for tool in self.tools}
        return self

    def rebuild_tasks(self, query: str, llm: BaseLanguageModel, file_dir: str, sop: str,
                      exec_config: ExecConfig, file_list: list[str], file_list_str: str = '') -> None:
        res = []
        child_map = {}  # task_id: [child_task]
        first_task = True
        for task in self.tasks:
            if not isinstance(task, dict):
                raise TypeError(f"Task must be an instance of dict, not {type(task)}")
            if self.task_mode == TaskMode.FUNCTION.value:
                task_instance = Task(**task,
                                     query=query,
                                     task_manager=self,
                                     llm=llm,
                                     file_dir=file_dir,
                                     finally_sop=sop,
                                     exec_config=exec_config,
                                     file_list=file_list,
                                     file_list_str=file_list_str)
            else:
                task_instance = ReactTask(**task,
                                          query=query,
                                          task_manager=self,
                                          llm=llm,
                                          file_dir=file_dir,
                                          finally_sop=sop,
                                          exec_config=exec_config,
                                          file_list=file_list,
                                          file_list_str=file_list_str)
            task_instance.first_task = first_task
            first_task = False
            if task_instance.parent_id is None:
                res.append(task_instance)
                continue
            if task_instance.parent_id not in child_map:
                child_map[task_instance.parent_id] = []
            child_map[task_instance.parent_id].append(task_instance)
        for one in res:
            if one.id in child_map:
                one.children = child_map[one.id]

        self.tasks = res
        self.task_map = {}
        self.task_step_map = {}
        for task in self.tasks:
            self.task_map[task.id] = task
            self.task_step_map[task.step_id] = task

    def get_all_task_info(self) -> list[dict]:
        """
        Retrieve all tasks managed by the task manager.
        :return: List of task information.
        """
        res = []
        sub_task = []
        for one in self.tasks:
            res.append(one.get_task_info())
            if one.children:
                for child in one.children:
                    sub_task.append(child.get_task_info())
        # 将子任务信息也添加到结果中
        res.extend(sub_task)
        return res

    @cached_property
    def get_all_tool_schema(self) -> list[dict]:
        """
        Retrieve all tools managed by the tool manager.
        :return: List of tools input schema.
        """
        # 所有tool的schema里增加一个`call_reason`的必填字段，让模型总结下为啥需要使用这个工具
        res = []
        for one in self.tools:
            schema = convert_to_openai_tool(one)
            if "call_reason" not in schema["function"]["parameters"]["properties"]:
                # 所有的工具都加一个调用原因的字段
                schema["function"]["parameters"]["properties"]["call_reason"] = {
                    "type": "string",
                    "description": "The reason for calling this tool, generated by the model."
                }
                if "required" not in schema["function"]["parameters"]:
                    schema["function"]["parameters"]["required"] = []
                schema["function"]["parameters"]["required"].append("call_reason")

            res.append(schema)
        res.append({
            "type": "function",
            "function": {
                "name": CallUserInputToolName,
                "description": "在你需要用户帮助或需要用户补充信息或确认内容的时候调用此工具，注意询问用户的时候不能使用回答。例如解决问题的规划，执行一个比较耗时的操作，并且请说明需要人类的原因。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "call_reason": {
                            "type": "string",
                            "description": "你需要在这里总结询问的前因后果，并生成问题询问用户。"
                        }
                    },
                },
                "required": [
                    "call_reason"
                ]
            }
        })
        return res

    @cached_property
    def get_all_tool_schema_str(self) -> str:
        """
        Retrieve all tools managed by the tool manager as a JSON string.
        :return: JSON string of tools input schema.
        """
        return json.dumps(self.get_all_tool_schema, ensure_ascii=False, indent=2)

    async def ainvoke_tool(self, name: str, params: dict) -> (str, bool):
        """
        Add a new tool to the tool manager.
        :param name: The name of the tool to be executed.
        :param params: The params of the tool to be invoked.
        :return: A tuple containing the result of the tool execution and a boolean indicating success.
        """
        if name not in self.tool_map:
            return f"tool {name} exec error, because tool name is not found", False
        if not params.get("call_reason"):
            return f"tool {name} exec error, because call_reason field is required.", False
        params.pop("call_reason")
        start_time = time.time()
        try:
            res = await self.tool_map[name].ainvoke(input=params)
            if not isinstance(res, str):
                res = str(res)
            return res, True
        except Exception as e:
            traceback.print_exc()
            return f"tool {name} exec error, something went wrong: {str(e)}", False
        finally:
            end_time = time.time()
            print(f"tool {name} exec time: {end_time - start_time:.5f} seconds")

    @classmethod
    def completion_task_tree_info(cls, original_task: list[dict]) -> list[dict]:
        """
        目前只支持一级任务串行！！！
        将模型生成的任务列表转换为完整的任务树信息，补全下游节点的信息
        """
        task_map = {}
        task_step_map = {}
        root_task = []
        no_root_task = []
        need_input_task = {}  # step_id: {task}
        for one in original_task:
            one["id"] = generate_uuid_str()
            task_map[one["id"]] = one
            task_step_map[one["step_id"]] = one

            # 不需要其他任务输入，或者只需要用户问题的 属于根节点
            if not one.get("input") or (len(one.get("input")) == 1 and one["input"][0] == "query"):
                root_task.append(one)
            else:
                # 需要其他任务输入的 属于非根节点。记录下需要哪些任务的输入
                for input_key in one["input"]:
                    if input_key == "query":
                        continue
                    if input_key not in need_input_task:
                        need_input_task[input_key] = set()
                    need_input_task[input_key].add(one["id"])
        # 补充下游节点的信息
        for one in original_task:
            if need_input_task.get(one["step_id"]):
                one["next_id"] = list(need_input_task[one["step_id"]])
            one['display_target'] = one.get('target')
            one['sop'] = one.get('workflow', '')
        return original_task

    def add_tasks(self, tasks: list[Task | ReactTask]) -> None:
        """
        when generate subtasks call this method.
        Add a list of tasks to the task manager.
        :param tasks: List of Task instances to be added.

        """
        for task in tasks:
            self.task_map[task.id] = task

    async def get_step_answer(self, step_id: str) -> str:
        """ 获取某个步骤的答案 """
        if step_id not in self.task_step_map:
            return f"not found step_id: {step_id}"
        return await self.task_step_map[step_id].get_answer()

    def get_processed_steps(self):
        """Get the steps that have been processed."""
        success_steps = []
        for task in self.tasks:
            if task.status == TaskStatus.SUCCESS.value:
                success_steps.append(task.step_id)
        return "你现在已经完成了" + ",".join(success_steps) if success_steps else ''

    def get_depend_step(self, step_id: str) -> str:
        depend_steps = []
        if step_id not in self.task_step_map:
            return ""
        task = self.task_step_map[step_id]
        next_ids = task.next_id
        while next_ids:
            new_next_ids = []
            for next_id in next_ids:
                if next_id not in self.task_map:
                    continue
                next_task = self.task_map[next_id]
                depend_steps.append(next_task.step_id)
                if next_task.next_id:
                    new_next_ids.extend(next_task.next_id)
            next_ids = new_next_ids
        return ",".join(list(set(depend_steps)))

    def get_step_list(self):
        res = []
        for task in self.tasks:
            if task.parent_id:
                continue
            res.append({
                'step_id': task.step_id,
                'target': task.target,
                'description': task.description
            })
        return res

    async def catch_task_exception(self, task: Task) -> None:
        try:
            await task.ainvoke()
        except Exception as e:
            task.status = TaskStatus.FAILED.value
            task.answer.append(str(e)[:-100])
            raise e

    async def remake_task_history(self, prompt: str, response: str, step_info: dict) -> None:
        """ 重新修改任务的上下文状态 """
        step_type = step_info['step_type']
        task_id = step_info['step_info']['task_id']

        if step_type == "generate_sub_task":
            # 如果是生成子任务，则将此任务的状态重置为等待执行，并清理后续任务的 上下文和子任务
            task_instance = self.task_map.get(task_id)
            task_instance.children = []

            # 解析新的模型返回为子任务列表并赋值
            task_list_info = await task_instance.parse_sub_tasks_info(response)
            task_instance.children = await task_instance.generate_sub_tasks(task_list_info)

            self.add_tasks(task_instance.children)
            task_instance.status = TaskStatus.WAITING.value
        elif step_type == "task_exec":
            # 则将此任务的状态重置为等待执行，并清理后续任务的 上下文和子任务
            task_instance = self.task_map.get(task_id)
            all_history_index = step_info['step_info']['all_history_index']
            history_index = step_info['step_info']['history_index']
            if all_history_index >= len(task_instance.all_history):
                # 说明直接截取最新的上下文长度即可
                task_instance.history = task_instance.history[:history_index]
            else:
                task_instance.all_history = task_instance.all_history[:all_history_index]
                task_instance.history = task_instance.history[:history_index]
            new_message, _ = await task_instance.parse_react_result(response)
            task_instance.history.append(new_message)
            task_instance.status = TaskStatus.WAITING.value
        else:
            raise Exception(f"{step_type} is not supported")

        # 清理后续任务的上下文和子任务
        is_clear = False
        for task in self.tasks:
            if is_clear:
                task.status = TaskStatus.WAITING.value
                task.answer = []
                task.history = []
                task.all_history = []
                task.children = []
                continue

            if task.id == task_id:
                is_clear = True
                continue
            elif task.children:
                for sub_task in task.children:
                    if is_clear:
                        sub_task.status = TaskStatus.WAITING.value
                        sub_task.answer = []
                        sub_task.history = []
                        sub_task.all_history = []
                        sub_task.children = []
                    if sub_task.id == task_id:
                        is_clear = True
                        continue

    async def ainvoke_task(self) -> AsyncIterator[BaseEvent]:
        for task in self.tasks:
            if task.status != TaskStatus.WAITING.value:
                continue
            async_task = asyncio.create_task(self.catch_task_exception(task))
            while not async_task.done():
                while not self.aqueue.empty():
                    res = await self.aqueue.get()
                    yield res
                await asyncio.sleep(0.1)
            while not self.aqueue.empty():
                res = await self.aqueue.get()
                yield res
            if task_exception := async_task.exception():
                raise task_exception
            if task.status == TaskStatus.FAILED.value:
                raise Exception(f"Task {task.step_id} failed with error: {task.get_finally_answer()}")

    async def continue_task(self, task_id: str, user_input: str) -> None:
        """
        Continue processing a specific task by its ID.
        :param task_id: The ID of the task to continue.
        :param user_input: User input to be processed in the task.
        """
        if task_id not in self.task_map:
            raise ValueError(f"Task with ID {task_id} not found.")

        await self.task_map[task_id].handle_user_input(user_input)
