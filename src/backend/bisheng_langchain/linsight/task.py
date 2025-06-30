import datetime
import json
from typing import List, Optional

from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field

from bisheng_langchain.linsight.const import TaskStatus, DefaultToolBuffer
from bisheng_langchain.linsight.prompt import SingleAgentPrompt, SummarizeHistoryPrompt, LoopAgentSplitPrompt
from bisheng_langchain.linsight.utils import encode_str_tokens, extract_code_blocks


class BaseTask(BaseModel):
    query: str = Field(..., description='用户问题')
    file_dir: str = Field(default="", description='存储文件的目录')
    llm: BaseLanguageModel = Field(..., description='Language model to use for processing queries')
    finally_sop: str = Field(default="", description="最终的SOP，用于处理任务的最终结果。")
    max_steps: int = Field(default=10, description='最大步骤数，超过这个数会报错')

    tool_buffer: int = Field(default=DefaultToolBuffer, description='工具缓冲区，用于存储工具调用的结果')
    history: List[BaseMessage] = Field(default_factory=list, description='原始聊天记录，包含user、tool、AI消息')
    status: str = Field(TaskStatus.WAITING.value, description='任务状态')
    answer: str = Field(default='', description='任务答案，最终的结果')
    task_manager: Optional["TaskManage"] = Field(None, description='Task manager for handling tasks and workflows')

    # llm generate task field
    step_id: str = Field(default='', description='Step ID')
    target: str = Field(default='', description='任务目标')
    sop: str = Field(default='', description='任务SOP，子任务的当前方法')
    node_loop: bool = Field(False, description='是否循环，循环的话需要生成子任务去执行')
    profile: str = Field(default='', description='任务角色')
    description: str = Field(default='', description='任务描述')
    prompt: str = Field(default='', description='任务的prompt')
    input: list[str] = Field(default_factory=list,
                             description='任务输入，必须是前置步骤的step_id或"query",可以多个。"query"代表用户的原始问题')

    def get_input_str(self) -> str:
        if not self.input:
            return ""
        input_str = ""
        for key in self.input:
            if key == "query":
                continue
            step_answer = self.task_manager.get_step_answer(key)
            input_str += f"{key}: \"{step_answer}\"\n"
        if input_str:
            input_str = f"输入：\n{input_str}"
        return input_str

    def build_system_message(self) -> BaseMessage:
        """
        Build the system message for the task.
        :return: The system message as a BaseMessage object.
        """
        if self.node_loop:
            pass
        prompt = SingleAgentPrompt.format(profile=self.profile,
                                          current_time=datetime.datetime.now().isoformat(),
                                          file_dir=self.file_dir,
                                          query=self.query,
                                          sop=self.finally_sop,
                                          workflow=self.task_manager.get_workflow(),
                                          processed_steps=self.task_manager.get_processed_steps(),
                                          input_str=self.get_input_str(),
                                          step_id=self.step_id,
                                          target=self.target,
                                          single_sop=self.sop)
        return SystemMessage(content=prompt)

    async def summarize_history(self, messages_str: str) -> str:
        """
        调用LLM总结历史记录,去除细节,保留关键信息

        Args:
            messages_str: 历史记录文本

        Returns:
            总结后的历史记录
        """
        # This is a placeholder for the actual summarization logic.
        # You would typically call an LLM or a summarization service here.
        # For now, we will just return a truncated version of the messages_str.
        prompt = SummarizeHistoryPrompt.format(sop=self.sop, query=self.query, history_str=messages_str)
        res = await self._ainvoke_llm_without_tools([HumanMessage(content=prompt)])
        return res.content

    async def build_messages_with_history(self) -> list[BaseMessage]:
        messages = []
        system_message = self.build_system_message()
        messages.append(system_message)

        if not self.history:
            return messages

        # 如果有聊天历史记录, 需要对工具消息做精简
        all_tool_messages = []
        all_remain_messages = []
        for one in self.history:
            if 'tool_calls' in one.additional_kwargs or isinstance(one, ToolMessage):
                all_tool_messages.append(one)
            else:
                all_remain_messages.append(one)
        all_tool_messages_str = json.dumps(all_tool_messages, ensure_ascii=False, indent=2)
        if len(encode_str_tokens(all_tool_messages_str)) > self.tool_buffer:
            messages_str = json.dumps(messages, ensure_ascii=False, indent=2)
            history_summary = await self.summarize_history(messages_str)
            all_remain_messages.append(AIMessage(content=history_summary))
            return all_remain_messages

        return messages

    async def _ainvoke_llm(self, messages: list[BaseMessage]) -> BaseMessage:
        """
        Invoke the language model with the provided messages.
        :param messages: List of messages to be sent to the language model.
        :return: The response from the language model.
        """
        # get tool schema
        tool_args = self.tool_manager.get_all_input_schema()
        return await self.llm.ainvoke(messages, tools=tool_args)

    async def _ainvoke_llm_without_tools(self, messages: list[BaseMessage]) -> BaseMessage:
        """
        Invoke the language model without tools.
        :param messages: List of messages to be sent to the language model.
        :return: The response from the language model.
        """
        return await self.llm.ainvoke(messages)


class Task(BaseTask):
    """
    Represents a task in the Lingsi agent system.
    This class is used to define the structure of a task,
    including its ID, name, description, and status.
    """

    children: list['SubTask'] = []  # List of child tasks, if is loop agent

    async def ainvoke(self) -> None:
        """
        Execute the task.
        This method should contain the logic to perform the task's operation.
        """
        self.status = TaskStatus.PROCESSING.value
        if self.node_loop:
            return await self.loop_invoke()

        for i in range(self.max_steps):
            messages = await self.build_messages_with_history()
            res = await self._ainvoke_llm(messages)
            self.history.append(res)
            if "tool_calls" in res.additional_kwargs and res.tool_calls:
                for one in res.tool_calls:
                    tool_name = one.get("name")
                    tool_args = one.get("args")
                    tool_result = await self.tool_manager.ainvoke_tool(tool_name, tool_args)
                    self.history.append(ToolMessage(name=tool_name, content=tool_result, tool_call_id=one.get("id")))
            else:  # 不需要工具调用说明输出了最终答案，执行结束
                break
        if isinstance(self.history[-1], AIMessage):
            self.status = TaskStatus.SUCCESS.value
            self.answer = self.history[-1].content
        else:
            self.status = TaskStatus.FAILED.value
        return None

    async def ainvoke_loop(self):
        """
        Execute the sub task in a loop.
        This method should contain the logic to perform the task's operation in a loop.
        """
        # generate sub-tasks based on the loop condition
        if not self.children:
            sub_task = await self.generate_sub_tasks()

        self.status = "in_progress"
        # Add loop execution logic here
        self.status = "completed"
        return None

    async def generate_sub_tasks(self) -> List['SubTask']:
        """
        Generate sub-tasks based on the current task.
        This method should contain the logic to create sub-tasks.
        :return: List of generated sub-tasks.
        """
        prompt = LoopAgentSplitPrompt.format(query=self.query, sop=self.sop,
                                             workflow=self.task_manager.get_workflow(),
                                             processed_steps=self.task_manager.get_processed_steps(),
                                             input_str=self.get_input_str(),
                                             prompt=self.prompt)
        messages = [HumanMessage(content=prompt)]
        res = await self._ainvoke_llm_without_tools(messages)
        # 解析生成的任务json数据
        json_str = extract_code_blocks(res.content)
        try:
            sub_task = json.loads(json_str)
        except json.decoder.JSONDecodeError:
            raise ValueError(f"Invalid JSON format in response: {json_str}")

        original_query = sub_task.get("总体任务目标", "")
        original_method = sub_task.get("总体方法", "")
        original_done = sub_task.get("已经完成的内容", "")
        sub_task_list = sub_task.get("任务列表", [])
        res = []
        for one in sub_task_list:
            res.append(SubTask(**self.model_dump(exclude={"children", "history", "status"}),
                               original_query=original_query,
                               original_method=original_method,
                               original_done=original_done,
                               )
                       )


class SubTask(BaseTask):
    """
    Represents a sub-task in the Lingsi agent system.
    This class is used to define the structure of a sub-task,
    which inherits from the Task class.
    """
    original_query: str = Field(default='', description='整体任务目标')
    original_method: str = Field(default='', description='整体任务方法')
    original_done: str = Field(default='', description='已完成的内容')
    last_answer: str = Field(default='', description='上一步骤的答案')

    parent_step_id: str = Field(default='', description='Parent step ID for the sub-task')

    async def invoke(self):
        """
        Execute the sub-task.
        This method should contain the logic to perform the sub-task's operation.
        """
        self.status = "in_progress"
        # Add sub-task execution logic here
        self.status = "completed"
