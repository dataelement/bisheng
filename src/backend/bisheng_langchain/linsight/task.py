import asyncio
import copy
import datetime
import json
import os
import time
from abc import abstractmethod
from typing import List, Optional, Any

import aiofiles
from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage, AIMessage
from langchain_openai.chat_models.base import _convert_message_to_dict
from pydantic import BaseModel, Field, ConfigDict, model_validator

from bisheng_langchain.linsight.const import TaskStatus, CallUserInputToolName, ExecConfig
from bisheng_langchain.linsight.event import ExecStep, GenerateSubTask, BaseEvent, NeedUserInput, TaskStart, TaskEnd
from bisheng_langchain.linsight.prompt import SingleAgentPrompt, SummarizeHistoryPrompt, LoopAgentSplitPrompt, \
    LoopAgentPrompt, SummarizeAnswerPrompt, SplitEvent
from bisheng_langchain.linsight.utils import encode_str_tokens, generate_uuid_str, \
    record_llm_prompt, extract_json_from_markdown, get_model_name_from_llm, record_linsight_event


class BaseTask(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(..., description='Unique ID')
    parent_id: Optional[str] = Field(default=None, description='父任务id，有则说明是二级任务')
    next_id: Optional[list[str]] = Field(default=None, description='依赖当前任务的任务id列表')
    first_task: bool = Field(default=False, description='是否是第一个任务，有些逻辑需要知道是否是首个任务')

    query: str = Field(..., description='用户问题')
    file_dir: str = Field(default="", description='存储文件的目录')
    llm: BaseLanguageModel = Field(..., description='Language model to use for processing queries')
    finally_sop: str = Field(default="", description="最终的SOP，用于处理任务的最终结果。")

    history: List[BaseMessage] = Field(default_factory=list, description='原始聊天记录，包含user、tool、AI消息')
    all_history: List[List[BaseMessage]] = Field(default_factory=list, description='包含总结消息的所有聊天记录')
    status: str = Field(TaskStatus.WAITING.value, description='任务状态')
    answer: list[Any] = Field(default_factory=list, description='任务答案，最终的结果')
    summarize_answer: Optional[str] = Field(default=None, description='总结后的答案，主要用于其他任务获取最终结果')
    task_manager: Optional[Any] = Field(None, description='Task manager for handling tasks and workflows')
    user_input: Optional[str] = Field(default=None, description='用户输入的内容')
    exec_config: ExecConfig = Field(default_factory=ExecConfig, description='执行过程中的配置')
    file_list: Optional[list[str]] = Field(default_factory=list, description='用户上传的所有文件列表')
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

    @model_validator(mode="before")
    @classmethod
    def validate_task(cls, values: dict) -> dict:
        # Convert all string fields to str type, because llm may generate them as int or other types
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
        if values.get("precautions"):
            values["precautions"] = str(values["precautions"])
        if not values.get("display_target"):
            values["display_target"] = values.get("target", "")
        else:
            values["display_target"] = str(values["display_target"])
        if values.get("original_query"):
            values["original_query"] = str(values["original_query"])
        if values.get("original_method"):
            values["original_method"] = str(values["original_method"])
        if values.get("original_done"):
            values["original_done"] = str(values["original_done"])
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
            input_str += f"<{key}的输出>\n{step_answer}\n</{key}的输出>\n"
        if input_str:
            input_str = f"输入：\n{input_str}"
        return input_str

    async def _base_ainvoke_tool(self, tool_name: str, tool_params: Any) -> (str, bool):
        start_time = time.time()
        observation, flag = await self.task_manager.ainvoke_tool(tool_name, copy.deepcopy(tool_params))
        if self.exec_config.debug:
            record_linsight_event(self.exec_config.debug_id, "tool_invoke", tool_params, time.time() - start_time)
        return observation, flag

    async def _base_invoke_llm(self, llm: BaseLanguageModel, tools: Optional[list[dict]], messages: list[BaseMessage],
                               **kwargs) -> BaseMessage:
        for i in range(max(self.exec_config.retry_num, 1)):
            try:
                # get tool schema
                start_time = time.time()
                if tools:
                    res = await llm.ainvoke(messages, tools=tools, **kwargs)
                else:
                    res = await llm.ainvoke(messages, **kwargs)
                if self.exec_config.debug and res:
                    record_llm_prompt(llm, "\n".join([one.text() for one in messages]), res.text(),
                                      res, time.time() - start_time,
                                      self.exec_config.debug_id)
                return res
            except Exception as e:
                record_llm_prompt(llm, "\n".join([one.text() for one in messages]), str(e),
                                  None, time.time() - start_time,
                                  self.exec_config.debug_id)
                if i == self.exec_config.retry_num - 1:
                    raise e
                else:
                    await asyncio.sleep(self.exec_config.retry_sleep)
                    continue
        raise Exception("Failed to invoke LLM after retries.")

    async def _ainvoke_llm(self, messages: list[BaseMessage], **kwargs) -> BaseMessage:
        """
        Invoke the language model with the provided messages.
        :param messages: List of messages to be sent to the language model.
        :return: The response from the language model.
        """
        tools = self.task_manager.get_all_tool_schema
        return await self._base_invoke_llm(self.llm, tools, messages, **kwargs)

    async def _ainvoke_llm_without_tools(self, messages: list[BaseMessage], **kwargs) -> BaseMessage:
        """
        Invoke the language model without tools.
        :param messages: List of messages to be sent to the language model.
        :return: The response from the language model.
        """
        return await self._base_invoke_llm(self.llm, None, messages, **kwargs)

    async def _split_task_llm(self, messages: list[BaseMessage], **kwargs) -> BaseMessage:
        """
        Invoke the language model to split the task into subtasks.
        :param messages: List of messages to be sent to the language model.
        :return: The response from the language model containing the split tasks.
        """
        model_name = get_model_name_from_llm(llm=self.llm)
        # 目前只支持openai模型的json模式输出
        if model_name.startswith("gpt"):
            kwargs["response_format"] = SplitEvent
        return await self._base_invoke_llm(self.llm, None, messages, **kwargs)

    async def _get_all_files(self, dir_path: str) -> List[str]:
        """
        获取指定目录下的所有文件路径
        Get all file paths in the specified directory.
        :param dir_path: The directory path to search for files.
        :return: A list of file paths.
        """
        file_paths = []
        if not os.path.exists(dir_path):
            return file_paths
        for entry in os.scandir(dir_path):
            if entry.is_file():
                file_paths.append(entry.path)
            elif entry.is_dir():
                # 如果是目录，则递归获取子目录的文件
                sub_files = await self._get_all_files(entry.path)
                file_paths.extend(sub_files)
            else:
                raise FileNotFoundError
        return file_paths

    async def _get_file_content(self) -> str:
        """
        切分任务时获取文件内容
        Get the content of the files uploaded by the user.
        :return: A string containing the content of the files.
        """
        file_content = ""
        ignore_files = ""
        # 如果是第一个任务则获取用户上传的文件内容
        if self.first_task:
            if not self.file_list:
                return file_content
        else:
            # 否则获取中间过程产生的文件内容, 不包含用户上传的文件
            ignore_files = ";".join(self.file_list) if self.file_list else ""

        all_files = await self._get_all_files(self.file_dir)
        for one_file in all_files:
            one_file_name = os.path.basename(one_file)
            if one_file_name in ignore_files:
                continue
            one_file_content = ""
            async with aiofiles.open(one_file, mode="r", encoding="utf-8") as f:
                async for line in f:
                    one_file_content += line
                    if len(one_file_content) > self.exec_config.file_content_length:
                        one_file_content = one_file_content[:self.exec_config.file_content_length]
                        break
            if one_file_content:
                file_content += f"{one_file_name}文件内容:\n{one_file_content}\n\n"
        return file_content

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
            if one.status != TaskStatus.WAITING.value:
                continue
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
                                             file_content=await self._get_file_content(),
                                             prompt=self.target,
                                             precautions=self.precautions)
        messages = [HumanMessage(content=prompt)]
        for i in range(self.exec_config.retry_num):
            if i > 0:
                res = await self._split_task_llm(messages, temperature=self.exec_config.retry_temperature)
            else:
                res = await self._split_task_llm(messages)
            try:
                sub_task_list = await self.parse_sub_tasks_info(res.content)
                self.exec_config.prompt_manage.insert_prompt("\n".join([one.text() for one in messages]),
                                                             "generate_sub_task", {
                                                                 "task_id": self.id
                                                             })
                return sub_task_list
            except Exception as e:
                if i == self.exec_config.retry_num - 1:
                    raise e
                continue
        raise Exception("Failed to generate sub tasks after retries.")

    async def parse_sub_tasks_info(self, message: str) -> List[dict]:
        sub_task = extract_json_from_markdown(message)

        original_query = sub_task.get("总体任务目标", "")
        original_method = f'{sub_task.get("总体方法", "")}\n{sub_task.get("可用资源", "")}'
        original_done = str(sub_task.get("已经完成的内容", ""))
        sub_task_list = sub_task.get("任务列表", [])
        res = []
        for one in sub_task_list:
            parent_info = self.model_dump(
                exclude={"children", "history", "status", "target", "sop", "task_manager", "llm", "all_history"})
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
                    tool_result, _ = await self._base_ainvoke_tool(tool_name, tool_args)
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

    async def generate_sub_tasks(self, sub_tasks_info: list[dict] = None) -> list['Task']:
        if sub_tasks_info is None:
            sub_tasks_info = await self._get_sub_tasks()
        return [Task(**one) for one in sub_tasks_info]
