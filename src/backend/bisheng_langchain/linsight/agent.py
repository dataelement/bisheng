import json
import time
from datetime import datetime
from typing import Optional, AsyncIterator

from langchain_core.language_models import BaseLanguageModel
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field

from bisheng_langchain.linsight.const import TaskMode, ExecConfig
from bisheng_langchain.linsight.event import BaseEvent
from bisheng_langchain.linsight.manage import TaskManage
from bisheng_langchain.linsight.prompt import SopPrompt, FeedBackSopPrompt, GenerateTaskPrompt
from bisheng_langchain.linsight.utils import record_llm_prompt, extract_json_from_markdown, record_linsight_event


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
    exec_config: ExecConfig = Field(default_factory=ExecConfig, description='执行过程中所需的配置')
    sop: str = Field(default=None, description='Standard Operating Procedure (SOP) to be followed by the agent')
    file_list: Optional[list[str]] = Field(default=None, description='List of files uploaded by the user')
    knowledge_list: Optional[list[str]] = Field(default=None, description='List of knowledge bases to be considered')
    tasks: Optional[list[dict]] = Field(default_factory=list, description='List of tasks to be processed by the agent')

    async def parse_file_list_str(self, file_list: list[str]) -> str:
        file_list_str = ""
        if file_list:
            file_list_str = "\n".join(file_list[:self.exec_config.max_file_num])
            if len(file_list) > self.exec_config.max_file_num:
                file_list_str += f"\n用户上传了{len(file_list)}份文件，此处只展示{self.exec_config.max_file_num}份。都储存在./目录下。"
            file_list_str = f"<用户上传文件列表>\n{file_list_str}\n</用户上传文件列表>"
        return file_list_str

    @staticmethod
    async def parse_knowledge_list_str(knowledge_list: list[str]) -> str:
        knowledge_list_str = ""
        if knowledge_list:
            knowledge_list_str = "\n".join(knowledge_list)
            knowledge_list_str = f"<知识库列表>\n{knowledge_list_str}\n</知识库列表>"
        return knowledge_list_str

    async def _parse_sop_content(self, sop_prompt: str) -> AsyncIterator[ChatGenerationChunk]:
        # Add logic to process the SOP string
        start_time = time.time()
        one = None
        sop_flag = False
        sop_content = ""
        answer = ""
        split_tags = ["<Thought_END>", "</Thought_END>"]
        async for one in self.llm.astream(sop_prompt):
            answer += f"{one.content}"
            if sop_flag:
                yield one
                sop_content += one.content
                continue
            for split_tag in split_tags:
                if answer.find(split_tag) != -1:
                    sop_flag = True
                    sop_content = answer.split(split_tag)[-1].strip()
                    if sop_content:
                        one.content = sop_content
                        yield one
                    break
        if not sop_content:
            one.content = answer
            yield one
        if self.exec_config.debug and one:
            record_llm_prompt(self.llm, sop_prompt, answer, one,
                              time.time() - start_time, self.exec_config.debug_id)

    async def generate_sop(self, sop: str, file_list: list[str] = None, knowledge_list: list[str] = None) \
            -> AsyncIterator[ChatGenerationChunk]:
        """
        Generate a Standard Operating Procedure (SOP) based on the provided SOP string.
        :param sop: The SOP string to be processed.
        :param file_list: Optional list of files uploaded by the user.
        :param knowledge_list: Optional list of knowledge bases to be considered.

        :return: Processed SOP string.
        """
        tools_str = json.dumps([convert_to_openai_tool(one) for one in self.tools], ensure_ascii=False, indent=2)

        file_list_str = await self.parse_file_list_str(file_list)
        knowledge_list_str = await self.parse_knowledge_list_str(knowledge_list)

        sop_prompt = SopPrompt.format(query=self.query, sop=sop, tools_str=tools_str, file_list_str=file_list_str,
                                      knowledge_list_str=knowledge_list_str)
        self.exec_config.prompt_manage.insert_prompt(sop_prompt, "generate_sop", None)
        # Add logic to process the SOP string
        async for one in self._parse_sop_content(sop_prompt):
            yield one

    async def feedback_sop(self, sop: str, feedback: str, history_summary: list[str] = None,
                           file_list: list[str] = None, knowledge_list: list[str] = None) \
            -> AsyncIterator[ChatGenerationChunk]:
        """
        Provide feedback on the generated SOP.
        :param sop: The SOP string to be reviewed.
        :param feedback: Feedback string for the SOP.
        :param history_summary: Optional summary of previous interactions.
        :param file_list: Optional list of files uploaded by the user.
        :param knowledge_list: Optional list of knowledge bases to be considered.

        :return: Processed SOP with feedback applied.
        """
        # Add logic to process the feedback on the SOP
        if history_summary:
            history_summary = "\n".join(history_summary)
        else:
            history_summary = ""
        tools_str = json.dumps([convert_to_openai_tool(one) for one in self.tools], ensure_ascii=False, indent=2)

        file_list_str = await self.parse_file_list_str(file_list)
        knowledge_list_str = await self.parse_knowledge_list_str(knowledge_list)

        sop_prompt = FeedBackSopPrompt.format(query=self.query, sop=sop, feedback=feedback, tools_str=tools_str,
                                              history_summary=history_summary, file_list_str=file_list_str,
                                              knowledge_list_str=knowledge_list_str)
        async for one in self._parse_sop_content(sop_prompt):
            yield one

    async def generate_task(self, sop: str) -> list[dict]:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tools_str = json.dumps([convert_to_openai_tool(one) for one in self.tools], ensure_ascii=False, indent=2)

        prompt = GenerateTaskPrompt.format(query=self.query, sop=sop, file_dir=self.file_dir,
                                           current_time=current_time, tools_str=tools_str)
        start_time = time.time()
        self.exec_config.prompt_manage.insert_prompt(prompt, "generate_task", None)
        res = await self.llm.ainvoke(prompt)
        if self.exec_config.debug and res:
            record_llm_prompt(self.llm, prompt, res.content, res,
                              time.time() - start_time, self.exec_config.debug_id)

        # 解析生成的任务json数据
        task = extract_json_from_markdown(res.content)
        tasks = task.get('steps', [])

        return TaskManage.completion_task_tree_info(tasks)

    async def ainvoke(self, tasks: list[dict], sop: str, file_list: list[str] = None) -> AsyncIterator[BaseEvent]:
        """
        Run the agent's main functionality.
        :param tasks: List of tasks to be processed by the agent.
        :param sop: Final SOP to be used in the agent's processing.
        :param file_list: Optional list of files uploaded by the user.
        """
        file_list_str = await self.parse_file_list_str(file_list)
        start_time = time.time()
        # Add main functionality logic here
        if not self.task_manager:
            self.task_manager = TaskManage(tasks=tasks, tools=self.tools, task_mode=self.task_mode)
            self.task_manager.rebuild_tasks(query=self.query, llm=self.llm, file_dir=self.file_dir, sop=sop,
                                            exec_config=self.exec_config, file_list=file_list,
                                            file_list_str=file_list_str)

        async for one in self.task_manager.ainvoke_task():
            yield one
        if self.exec_config.debug:
            record_linsight_event(self.exec_config.debug_id, "agent_over", "", time.time() - start_time)

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

    async def ainvoke_to_end(self, sop: str, file_list: list[str] = None, knowledge_list: list[str] = None) \
            -> AsyncIterator[BaseEvent]:
        """
        Run the agent's main functionality without predefined tasks.
        :param sop: 参考 SOP 用来生成新的sop
        :param file_list: Optional list of files uploaded by the user.
        :param knowledge_list: list[str] = None
        """
        if not self.file_list:
            self.file_list = file_list
        if not self.knowledge_list:
            self.knowledge_list = knowledge_list
        # 1、生成sop
        if not self.sop:
            sop_content = ""
            async for one in self.generate_sop(sop, file_list, knowledge_list):
                sop_content += one.content
                pass
            self.sop = sop_content

        # 2、生成任务
        if not self.tasks:
            tasks = await self.generate_task(self.sop)
            self.tasks = tasks

        # 3、执行任务
        async for one in self.ainvoke(self.tasks, self.sop, file_list):
            yield one

    async def ainvoke_by_prompt(self, prompt: str, response: str) -> AsyncIterator[BaseEvent]:
        """
        从prompt对应的节点开始执行灵思agent
        """
        step_info = self.exec_config.prompt_manage.get_prompt_info(prompt)
        if not step_info:
            raise Exception("未找到prompt对应的任务节点")
        # 从生成sop开始
        if step_info['step_type'] == 'generate_sop':
            if response.find("<Thought_END>") != -1:
                response = response.split("<Thought_END>", 1)[-1].strip()
            elif response.find("</Thought_END>") != -1:
                response = response.split("</Thought_END>", 1)[-1].strip()
            self.sop = response
            self.tasks = []
            self.task_manager = None
            async for one in self.ainvoke_to_end(''):
                yield one
            return
        elif step_info['step_type'] == 'generate_task':
            # 从生成任务开始
            self.tasks = extract_json_from_markdown(response).get('steps', [])
            self.task_manager = None
            async for one in self.ainvoke_to_end(""):
                yield one
            return

        # 先修改任务的上下文状态
        await self.task_manager.remake_task_history(prompt, response, step_info)

        # 从某个任务某个步骤开始执行
        task_id = step_info['step_info']['task_id']
        if task_id not in self.task_manager.task_map:
            raise Exception(f"未找到任务ID对应的任务: {task_id}")
