import asyncio
import copy
import datetime
import json
import time
from abc import abstractmethod
from typing import List, Optional, Any

from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage, AIMessage
from langchain_openai.chat_models.base import _convert_message_to_dict
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

from bisheng_langchain.linsight.const import TaskStatus, CallUserInputToolName, ExecConfig
from bisheng_langchain.linsight.event import ExecStep, GenerateSubTask, BaseEvent, NeedUserInput, TaskStart, TaskEnd
from bisheng_langchain.linsight.prompt import SingleAgentPrompt, SummarizeHistoryPrompt, LoopAgentSplitPrompt, \
    LoopAgentPrompt, SummarizeAnswerPrompt
from bisheng_langchain.linsight.utils import encode_str_tokens, generate_uuid_str, \
    record_llm_prompt, extract_json_from_markdown


class BaseTask(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(..., description='Unique ID')
    parent_id: Optional[str] = Field(default=None, description='父任务id')
    next_id: Optional[list[str]] = Field(default=None, description='下一批任务的id列表')

    query: str = Field(..., description='用户问题')
    file_dir: str = Field(default="", description='存储文件的目录')
    llm: BaseLanguageModel = Field(..., description='Language model to use for processing queries')
    finally_sop: str = Field(default="", description="最终的SOP，用于处理任务的最终结果。")

    history: List[BaseMessage] = Field(default_factory=list, description='原始聊天记录，包含user、tool、AI消息')
    status: str = Field(TaskStatus.WAITING.value, description='任务状态')
    answer: list[Any] = Field(default_factory=list, description='任务答案，最终的结果')
    summarize_answer: Optional[str] = Field(default=None, description='总结后的答案，主要用于其他任务获取最终结果')
    task_manager: Optional[Any] = Field(None, description='Task manager for handling tasks and workflows')
    user_input: Optional[str] = Field(default=None, description='用户输入的内容')
    exec_config: ExecConfig = Field(default_factory=ExecConfig, description='执行过程中的配置')
    file_list_str: Optional[str] = Field(default='', description='用户上传的文件列表字符串')

    # llm generate task field
    step_id: str = Field(default='', description='Step ID')
    target: str = Field(default='', description='任务目标')
    display_target: str = Field(default='', validate_default=True, description='任务展示目标，给用户看的')
    sop: str = Field(default='', description='任务SOP，子任务的当前方法')
    node_loop: bool = Field(False, description='是否循环，循环的话需要生成子任务去执行')
    profile: str = Field(default='', description='任务角色')
    description: str = Field(default='', description='任务描述')
    prompt: Optional[str] = Field(default='', description='任务的prompt')
    precautions: Optional[str] = Field(default='', description='任务注意事项')
    workflow: Optional[str] = Field(default='', description='步骤的执行流程')
    input: list[str] = Field(default_factory=list,
                             description='任务输入，必须是前置步骤的step_id或"query",可以多个。"query"代表用户的原始问题')

    children: Optional[list['BaseTask']] = []  # List of child tasks, if is loop agent

    # sub task field
    original_query: Optional[str] = Field(default='', description='整体任务目标')
    original_method: Optional[str] = Field(default='', description='整体任务方法')
    original_done: Optional[str] = Field(default='', description='已完成的内容')
    last_answer: Optional[str] = Field(default='', description='上一步骤的答案，暂无用处')

    @field_validator("display_target", mode="before")
    @classmethod
    def auto_set_display_target(cls, v, values):
        if v is None or v == "":
            return values.data.get("target", "")
        return v

    @model_validator(mode="before")
    @classmethod
    def validate_task(cls, values: dict) -> dict:
        if values.get("target"):
            values["target"] = str(values["target"])
        if values.get("prompt"):
            values["prompt"] = str(values["prompt"])
        if values.get("step_id"):
            values["step_id"] = str(values["step_id"])
        if values.get("sop"):
            values["sop"] = str(values["sop"])
        if values.get("description"):
            values["description"] = str(values["description"])
        if values.get("profile"):
            values["profile"] = str(values["profile"])
        if values.get("workflow"):
            values["workflow"] = str(values["workflow"])
        return values

    def get_task_info(self) -> dict:
        return self.model_dump(exclude={"task_manager", "llm", "file_dir", "finally_sop", "children", "exec_config"})

    async def get_input_str(self) -> str:
        if not self.input:
            return ""
        input_str = ""
        for key in self.input:
            if key == "query":
                continue
            step_answer = await self.task_manager.get_step_answer(key)
            input_str += f"{key}: \"{step_answer}\"\n"
        if input_str:
            input_str = f"输入：\n{input_str}"
        return input_str

    async def _ainvoke_llm(self, messages: list[BaseMessage], **kwargs) -> BaseMessage:
        """
        Invoke the language model with the provided messages.
        :param messages: List of messages to be sent to the language model.
        :return: The response from the language model.
        """
        for i in range(max(self.exec_config.retry_num, 1)):
            try:
                # get tool schema
                tool_args = self.task_manager.get_all_tool_schema
                start_time = time.time()
                res = await self.llm.ainvoke(messages, tools=tool_args, **kwargs)
                if self.exec_config.debug and res:
                    record_llm_prompt(self.llm, "\n".join([one.text() for one in messages]), res.text(),
                                      res, time.time() - start_time,
                                      self.exec_config.debug_id)
                return res
            except Exception as e:
                if i == self.exec_config.retry_num - 1:
                    raise e
                else:
                    await asyncio.sleep(self.exec_config.retry_sleep)
                    continue
        raise Exception("Failed to invoke LLM after retries.")

    async def _ainvoke_llm_without_tools(self, messages: list[BaseMessage], **kwargs) -> BaseMessage:
        """
        Invoke the language model without tools.
        :param messages: List of messages to be sent to the language model.
        :return: The response from the language model.
        """
        for i in range(max(self.exec_config.retry_num, 1)):
            try:
                start_time = time.time()
                res = await self.llm.ainvoke(messages, **kwargs)
                if self.exec_config.debug and res:
                    record_llm_prompt(self.llm, "\n".join([one.text() for one in messages]), res.text(),
                                      res, time.time() - start_time,
                                      self.exec_config.debug_id)
                return res
            except Exception as e:
                if i == self.exec_config.retry_num - 1:
                    raise e
                else:
                    await asyncio.sleep(self.exec_config.retry_sleep)
                    continue
        raise Exception("Failed to invoke LLM after retries.")

    async def handle_user_input(self, user_input: str) -> None:
        """
        Handle user input for the task.
        This method should be called when the task is waiting for user input.
        :param user_input: The input provided by the user.
        """
        self.user_input = user_input
        self.status = TaskStatus.INPUT_OVER.value

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
        query = self.target
        if self.parent_id:
            query = self.target
        prompt = SummarizeHistoryPrompt.format(sop=self.sop, query=query, history_str=messages_str)
        res = await self._ainvoke_llm_without_tools([HumanMessage(content=prompt)])
        return res.content

    async def ainvoke_loop(self):
        """
        Execute the subtask in a loop.
        This method should contain the logic to perform the task's operation in a loop.
        """
        # generate sub-tasks based on the loop condition
        if not self.children:
            self.children = await self.generate_sub_tasks()
            self.task_manager.add_tasks(self.children)
            await self.put_event(GenerateSubTask(task_id=self.id,
                                                 subtask=[one.get_task_info() for one in self.children]))
        if not self.children:
            self.status = TaskStatus.SUCCESS.value
            return None
        # 如果是循环任务，子任务执行完毕后需要将结果合并。目前
        all_failed = True
        answer = []
        error = ""
        # _ = await asyncio.gather(*[one.ainvoke() for one in self.children])

        for one in self.children:
            await one.ainvoke()
            if one.status == TaskStatus.SUCCESS.value:
                all_failed = False
                answer.append(one.get_finally_answer())
            else:
                error += one.get_finally_answer() + "\n"
        self.status = TaskStatus.FAILED.value if all_failed else TaskStatus.SUCCESS.value
        self.answer.append(error) if all_failed else self.answer.extend(answer)
        return None

    async def _get_sub_tasks(self) -> List[dict]:
        """
        Generate subtasks based on the current task.
        This method should contain the logic to create subtasks.
        :return: List of generated subtasks.
        """
        prompt = LoopAgentSplitPrompt.format(query=self.query, sop=self.sop,
                                             step_list=self.task_manager.get_step_list(),
                                             processed_steps=self.task_manager.get_processed_steps(),
                                             input_str=await self.get_input_str(),
                                             prompt=self.target,
                                             precautions=self.precautions)
        messages = [HumanMessage(content=prompt)]
        sub_task = None
        for i in range(self.exec_config.retry_num):
            if i > 0:
                res = await self._ainvoke_llm_without_tools(messages, temperature=self.exec_config.retry_temperature)
            else:
                res = await self._ainvoke_llm_without_tools(messages)
            try:
                # 解析生成的任务json数据
                sub_task = extract_json_from_markdown(res.content)
                break
            except Exception as e:
                if i == self.exec_config.retry_num - 1:
                    raise e
                continue
        original_query = sub_task.get("总体任务目标", "")
        original_method = f'{sub_task.get("总体方法", "")}\n{sub_task.get("可用资源", "")}'
        original_done = str(sub_task.get("已经完成的内容", ""))
        sub_task_list = sub_task.get("任务列表", [])
        res = []
        for one in sub_task_list:
            parent_info = self.model_dump(
                exclude={"children", "history", "status", "target", "sop", "task_manager", "llm"})
            display_target = one.get("当前目标", "")
            target = f'{one.get("当前目标", "")}\n{one.get("输出方法", "")}'
            if one.get("标题层级", ""):
                target += f"\n标题层级要求: {one.get('标题层级', '')}"
            if one.get("标题层级类型", ""):
                target += f"\n标题层级类型: {one.get('标题层级类型', '')}"
            if one.get("思考", ""):
                target += f"\n思考: {one.get('思考', '')}"
            parent_info.update({
                "original_query": original_query,
                "original_method": original_method,
                "original_done": original_done,
                "target": target,
                "sop": one.get("当前方法", ""),
                "id": generate_uuid_str(),
                "parent_id": self.id,
                "task_manager": self.task_manager,
                "llm": self.llm,
                "display_target": display_target,
            })
            res.append(parent_info)
        return res

    async def put_event(self, event: BaseEvent) -> None:
        if not self.task_manager:
            raise RuntimeError('Task manager not initialized.')
        if not self.task_manager.aqueue:
            raise RuntimeError('Task manager queue not initialized.')
        self.task_manager.aqueue.put_nowait(event)

    @abstractmethod
    async def _ainvoke(self):
        raise NotImplementedError

    async def ainvoke(self) -> None:
        await self.put_event(TaskStart(task_id=self.id, name=self.profile))
        try:
            await self._ainvoke()
        except Exception as e:
            self.status = TaskStatus.FAILED.value
            self.answer.append(f"task exec failed: {str(e)[-100:]}")
            raise e
        finally:
            await self.put_event(
                TaskEnd(task_id=self.id, status=self.status, name=self.profile, answer=self.get_finally_answer(),
                        data=self.get_task_info()))

    @abstractmethod
    async def get_history_str(self) -> str:
        raise NotImplementedError

    async def get_answer(self) -> str:
        if self.summarize_answer:
            return self.summarize_answer

        # 如果有子任务，拼接所有子任务的答案
        if self.children:
            self.summarize_answer = "\n".join([await one.get_answer() for one in self.children])
            return self.summarize_answer

        if not self.history:
            return ""

        prompt_str = SummarizeAnswerPrompt.format(history_str=await self.get_history_str(),
                                                  step_list=self.task_manager.get_step_list(),
                                                  step_id=self.step_id,
                                                  depend_step=self.task_manager.get_depend_step(self.step_id))
        res = await self._ainvoke_llm_without_tools([HumanMessage(content=prompt_str)])
        self.summarize_answer = res.content
        return self.summarize_answer

    def get_finally_answer(self) -> str:
        """
        Get the final answer of the task.
        This method returns the last answer in the answer list.
        :return: The final answer as a string.
        """
        if self.answer:
            return str(self.answer[-1])
        return ""


class Task(BaseTask):
    """
    Represents a task in the Lingsi agent system.
    This class is used to define the structure of a task,
    including its ID, name, description, and status.
    """

    async def get_history_str(self) -> str:
        history_list = await self.build_messages_with_history()
        # 首条是sop的描述，不需要
        history_list = history_list[1:]
        return json.dumps([_convert_message_to_dict(one) for one in history_list], ensure_ascii=False, indent=2)

    async def build_system_message(self) -> BaseMessage:
        """
        Build the system message for the task.
        :return: The system message as a BaseMessage object.
        """
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H")
        # 说明是二级子任务
        if self.node_loop and self.parent_id:
            prompt = LoopAgentPrompt.format(profile=self.profile,
                                            current_time=current_time,
                                            file_dir=self.file_dir,
                                            original_query=self.original_query,
                                            original_method=self.original_method,
                                            original_done=self.original_done,
                                            last_answer=await self.get_input_str(),
                                            single_sop=self.sop,
                                            step_id=self.step_id,
                                            target=self.target)
        else:
            prompt = SingleAgentPrompt.format(profile=self.profile,
                                              current_time=current_time,
                                              file_dir=self.file_dir,
                                              query=self.query,
                                              sop=self.finally_sop,
                                              step_list=self.task_manager.get_step_list(),
                                              processed_steps=self.task_manager.get_processed_steps(),
                                              input_str=await self.get_input_str(),
                                              step_id=self.step_id,
                                              target=self.target,
                                              single_sop=self.sop,
                                              precautions=self.precautions)
        return HumanMessage(content=prompt)

    async def build_messages_with_history(self) -> list[BaseMessage]:
        messages = []
        system_message = await self.build_system_message()
        messages.append(system_message)

        if not self.history:
            return messages

        messages.extend(self.history)

        # 如果有聊天历史记录, 需要对工具消息做精简
        all_tool_messages = []
        all_remain_messages = []
        for one in messages:
            if 'tool_calls' in one.additional_kwargs or isinstance(one, ToolMessage):
                all_tool_messages.append(one)
            else:
                all_remain_messages.append(one)
        all_tool_messages_str = json.dumps([one.model_dump() for one in all_tool_messages], ensure_ascii=False,
                                           indent=2)
        if len(encode_str_tokens(all_tool_messages_str)) > self.exec_config.tool_buffer:
            messages_str = json.dumps([one.model_dump() for one in messages], ensure_ascii=False, indent=2)
            history_summary = await self.summarize_history(messages_str)
            # 将总结后的历史记录插入到system_message后面
            all_remain_messages.append(AIMessage(content=history_summary))
            self.history = all_remain_messages
            return all_remain_messages
        return messages

    async def _ainvoke(self) -> None:
        """
        Execute the task.
        This method should contain the logic to perform the task's operation.
        """
        self.status = TaskStatus.PROCESSING.value
        if self.node_loop and not self.parent_id:
            return await self.ainvoke_loop()

        for i in range(self.exec_config.max_steps):
            messages = await self.build_messages_with_history()
            res = await self._ainvoke_llm(messages)
            self.history.append(res)
            print(res)
            if "tool_calls" in res.additional_kwargs and res.tool_calls:
                for one in res.tool_calls:
                    tool_name = one.get("name")
                    tool_args = one.get("args")
                    call_reason = tool_args.get("call_reason") if "call_reason" in tool_args else ""

                    # 等待用户输入的特殊工具调用
                    if tool_name == CallUserInputToolName:
                        # 等待用户输入
                        self.status = TaskStatus.INPUT.value
                        await self.put_event(NeedUserInput(task_id=self.id, call_reason=call_reason))
                        # 等待用户输入
                        while self.status != TaskStatus.INPUT_OVER.value:
                            await asyncio.sleep(0.5)

                        # 用户输入结束继续执行
                        self.status = TaskStatus.PROCESSING.value
                        self.history.append(
                            ToolMessage(name=tool_name, content=self.user_input, tool_call_id=one.get("id")))
                        self.user_input = None
                        break

                    # 正常工具调用
                    await self.put_event(ExecStep(task_id=self.id,
                                                  call_id=one.get('id'),
                                                  call_reason=call_reason,
                                                  name=tool_name,
                                                  params=tool_args,
                                                  status="start"))
                    tool_result, _ = await self.task_manager.ainvoke_tool(tool_name, copy.deepcopy(tool_args))
                    await self.put_event(ExecStep(task_id=self.id,
                                                  call_id=one.get('id'),
                                                  call_reason=call_reason,
                                                  name=tool_name,
                                                  params=tool_args,
                                                  output=tool_result,
                                                  status="end"))
                    self.history.append(ToolMessage(name=tool_name, content=tool_result, tool_call_id=one.get("id")))
            else:  # 不需要工具调用说明输出了最终答案，执行结束
                break
        if isinstance(self.history[-1], AIMessage):
            self.status = TaskStatus.SUCCESS.value
            self.answer.append(self.history[-1].content)
        else:
            self.status = TaskStatus.FAILED.value
            self.answer.append("task exec over max steps and not generate answer")
        return None

    async def generate_sub_tasks(self) -> list['Task']:
        sub_tasks_info = await self._get_sub_tasks()
        return [Task(**one) for one in sub_tasks_info]
