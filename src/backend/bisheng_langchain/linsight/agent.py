import json
import time
from datetime import datetime
from typing import Optional, AsyncIterator

from langchain_core.language_models import BaseLanguageModel
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field

from bisheng_langchain.linsight.const import TaskMode, MaxFileNum
from bisheng_langchain.linsight.event import BaseEvent
from bisheng_langchain.linsight.manage import TaskManage
from bisheng_langchain.linsight.prompt import SopPrompt, FeedBackSopPrompt, GenerateTaskPrompt
from bisheng_langchain.linsight.utils import record_llm_prompt, extract_json_from_markdown


class LinsightAgent(BaseModel):
    """
    Agent for Linsight, a service that provides various functionalities.
    """
    file_dir: Optional[str] = Field(default="", description='Directory for storing files')
    query: str = Field(..., description='user question')
    llm: BaseLanguageModel = Field(..., description='Language model to use for processing queries')

    tools: Optional[list[BaseTool]] = Field(default_factory=list,
                                            description='List of langchain tools to be used by the agent')
    task_manager: Optional[TaskManage] = Field(default=None,
                                               description='Task manager for handling tasks and workflows')
    task_mode: str = Field(default=TaskMode.FUNCTION.value,
                           description="Mode of the task execute")
    debug: Optional[bool] = Field(default=False, description='是否是调试模式。开启后会记录llm的输入和输出')
    debug_id: Optional[str] = Field(default=None, description='调试记录唯一ID, 用来写唯一的文件')

    @staticmethod
    async def parse_file_list_str(file_list: list[str]) -> str:
        file_list_str = ""
        if file_list:
            file_list_str = "\n".join(file_list[:MaxFileNum])
            file_list_str = f"用户上传文件列表:\n{file_list_str}\n"
            if len(file_list) > MaxFileNum:
                file_list_str += f"用户上传了{len(file_list)}份文件，此处只展示{MaxFileNum}份。都储存在./目录下。"
        return file_list_str

    async def generate_sop(self, sop: str, file_list: list[str] = None) -> AsyncIterator[ChatGenerationChunk]:
        """
        Generate a Standard Operating Procedure (SOP) based on the provided SOP string.
        :param sop: The SOP string to be processed.
        :param file_list: Optional list of files uploaded by the user.

        :return: Processed SOP string.
        """
        tools_str = json.dumps([convert_to_openai_tool(one) for one in self.tools], ensure_ascii=False, indent=2)

        file_list_str = await self.parse_file_list_str(file_list)

        sop_prompt = SopPrompt.format(query=self.query, sop=sop, tools_str=tools_str, file_list_str=file_list_str)
        # Add logic to process the SOP string
        start_time = time.time()
        one = None
        sop_flag = False
        sop_content = ""
        answer = ""
        async for one in self.llm.astream(sop_prompt):
            answer += f"{one.content}"
            if sop_flag:
                yield one
                sop_content += one.content
                continue
            if answer.find("<SOP_START>") != -1:
                sop_flag = True
                sop_content = answer.split("<SOP_START>")[-1].strip()
                if sop_content:
                    one.content = sop_content
                    yield one
        if not sop_content:
            one.content = answer
            yield one

        if self.debug and one:
            record_llm_prompt(self.llm, sop_prompt, answer, one.response_metadata.get('token_usage', None),
                              time.time() - start_time, self.debug_id)

    async def feedback_sop(self, sop: str, feedback: str, history_summary: list[str] = None,
                           file_list: list[str] = None) -> AsyncIterator[
        ChatGenerationChunk]:
        """
        Provide feedback on the generated SOP.
        :param sop: The SOP string to be reviewed.
        :param feedback: Feedback string for the SOP.
        :param history_summary: Optional summary of previous interactions.
        :param file_list: Optional list of files uploaded by the user.

        :return: Processed SOP with feedback applied.
        """
        # Add logic to process the feedback on the SOP
        if history_summary:
            history_summary = "\n".join(history_summary)
        else:
            history_summary = ""
        tools_str = json.dumps([convert_to_openai_tool(one) for one in self.tools], ensure_ascii=False, indent=2)
        if sop:
            sop = f"已有SOP：{sop}"

        file_list_str = await self.parse_file_list_str(file_list)

        sop_prompt = FeedBackSopPrompt.format(query=self.query, sop=sop, feedback=feedback, tools_str=tools_str,
                                              history_summary=history_summary, file_list_str=file_list_str)
        start_time = time.time()
        one = None
        answer = ''
        async for one in self.llm.astream(sop_prompt):
            answer += f"{one.content}"
            yield one
        if self.debug and one:
            record_llm_prompt(self.llm, sop_prompt, answer, one.response_metadata.get('token_usage', None),
                              time.time() - start_time, self.debug_id)

    async def generate_task(self, sop: str) -> list[dict]:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tools_str = self.task_manager.get_all_tool_schema_str
        prompt = GenerateTaskPrompt.format(query=self.query, sop=sop, file_dir=self.file_dir,
                                           current_time=current_time, tools_str=tools_str)
        start_time = time.time()
        res = await self.llm.ainvoke(prompt)
        if self.debug and res:
            record_llm_prompt(self.llm, prompt, res.content, res.response_metadata.get('token_usage', None),
                              time.time() - start_time, self.debug_id)

        # 解析生成的任务json数据
        task = extract_json_from_markdown(res.content)
        tasks = task.get('steps', [])

        return TaskManage.completion_task_tree_info(tasks)

    async def ainvoke(self, tasks: list[dict], sop: str) -> AsyncIterator[BaseEvent]:
        """
        Run the agent's main functionality.
        :param tasks: List of tasks to be processed by the agent.
        :param sop: Final SOP to be used in the agent's processing.
        """
        # Add main functionality logic here
        if not self.task_manager:
            self.task_manager = TaskManage(tasks=tasks, tools=self.tools, task_mode=self.task_mode)
            self.task_manager.rebuild_tasks(query=self.query, llm=self.llm, file_dir=self.file_dir, sop=sop,
                                            debug=self.debug, debug_id=self.debug_id)

        async for one in self.task_manager.ainvoke_task():
            yield one

    async def continue_task(self, task_id: str, user_input: str) -> None:
        """
        Continue processing a specific task by its ID.
        :param task_id: The ID of the task to continue.
        :param user_input: User input to be processed in the task.

        """
        if not self.task_manager:
            raise ValueError("Task manager is not initialized.")
        if task_id not in self.task_manager.task_map:
            raise ValueError(f"Task with ID {task_id} not found.")

        result = self.task_manager.continue_task(task_id, user_input)
        await result

    async def get_all_task_info(self) -> list[dict]:
        """
        Get all tasks managed by the agent.
        :return: List of all tasks info.
        """
        if not self.task_manager:
            return []
        return self.task_manager.get_all_task_info()
