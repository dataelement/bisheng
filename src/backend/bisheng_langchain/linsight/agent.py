import asyncio
import json
from datetime import datetime
from typing import Optional, AsyncIterator

from langchain_core.language_models import BaseLanguageModel
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from bisheng_langchain.linsight.manage import TaskManage
from bisheng_langchain.linsight.prompt import SopPrompt, FeedBackSopPrompt, GenerateTaskPrompt
from bisheng_langchain.linsight.tools.local_file import LocalFileTool
from bisheng_langchain.linsight.utils import extract_code_blocks


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

    async def generate_sop(self, sop: str) -> AsyncIterator[ChatGenerationChunk]:
        """
        Generate a Standard Operating Procedure (SOP) based on the provided SOP string.
        :param sop: The SOP string to be processed.
        :return: Processed SOP string.
        """
        sop_prompt = SopPrompt.format(query=self.query, sop=sop)
        # Add logic to process the SOP string
        async for one in self.llm.astream(sop_prompt):
            yield one

    async def feedback_sop(self, sop: str, feedback: str, history_summary: list[str] = None) -> AsyncIterator[
        ChatGenerationChunk]:
        """
        Provide feedback on the generated SOP.
        :param sop: The SOP string to be reviewed.
        :param feedback: Feedback string for the SOP.
        :param history_summary: Optional summary of previous interactions.

        :return: Processed SOP with feedback applied.
        """
        # Add logic to process the feedback on the SOP
        if history_summary:
            history_summary = "\n".join(history_summary)
        else:
            history_summary = ""
        sop_prompt = FeedBackSopPrompt.format(query=self.query, sop=sop, feedback=feedback,
                                              history_summary=history_summary)
        async for one in self.llm.astream(sop_prompt):
            yield one

    async def generate_task(self, sop: str) -> list[dict]:
        current_time = datetime.now().isoformat()
        prompt = GenerateTaskPrompt.format(query=self.query, sop=sop, file_dir=self.file_dir, current_time=current_time)
        res = await self.llm.ainvoke(prompt)

        # 解析生成的任务json数据
        json_str = extract_code_blocks(res.content)
        try:
            task = json.loads(json_str)
        except json.decoder.JSONDecodeError:
            raise ValueError(f"Invalid JSON format in response: {json_str}")
        return task.get('steps', [])

    async def invoke(self, tasks: list[dict], finally_sop: str) -> None:
        """
        Run the agent's main functionality.
        :param tasks: List of tasks to be processed by the agent.
        :param finally_sop: Final SOP to be used in the agent's processing.
        """
        # Add main functionality logic here
        self.task_manager = TaskManage(tasks=tasks, tools=self.tools, file_dir=self.file_dir, llm=self.llm,
                                       finally_sop=finally_sop)

        pass


if __name__ == '__main__':
    from langchain_community.chat_models import ChatTongyi
    from pydantic import SecretStr
    from bisheng_langchain.gpts.load_tools import load_tools

    used_tools = load_tools({
        "bing_search": {
            "bing_subscription_key": "231d87d51dba42bab16f03d44bbd0044",
            "bing_search_url": "https://api.bing.microsoft.com/v7.0/search",
        }
    })


    async def async_main():

        api_key = 'sk-141e3f6730b5449fb614e2888afd6c69'
        chat = ChatTongyi(api_key=SecretStr(api_key), model="qwen-max-latest", streaming=True)
        file_dir = "~/works/bisheng/src/backend/bisheng_langchain/linsight/data"

        # 获取本地文件相关工具
        used_tools.extend(LocalFileTool.get_all_tools(root_path=file_dir))
        query = "分析该目录下的简历文件（仅限txt格式），挑选出符合要求的简历。要求包括：python代码能力强，有大模型相关项目经验，有热情、主动性高"

        agent = LinsightAgent(llm=chat, query=query, tools=used_tools, file_dir=file_dir)

        # 生成sop
        sop = ""
        async for one in agent.generate_sop(""):
            sop += one.content
        print(f"first sop: {sop}")

        # # 反馈sop
        # feedback = "需要补充更多关于秦始皇兵马俑的历史背景信息"
        # feedback_sop = ""
        # async for one in agent.feedback_sop(sop, feedback, []):
        #     feedback_sop += one.content
        # print(f"feedback sop: {feedback_sop}")
        # sop=feedback_sop

        task_info = await agent.generate_task(sop)
        print(f"task_info: {task_info}")


    asyncio.run(async_main())
