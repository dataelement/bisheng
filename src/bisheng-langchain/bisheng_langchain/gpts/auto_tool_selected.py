from bisheng_langchain.gpts.prompts.select_tools_prompt import HUMAN_MSG, SYS_MSG
from langchain.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_core.language_models.base import LanguageModelLike
from pydantic import BaseModel


class ToolInfo(BaseModel):
    tool_name: str
    tool_description: str


class ToolSelector:

    def __init__(
        self,
        llm: LanguageModelLike,
        tools: list[ToolInfo],
        system_message: str = SYS_MSG,
        human_message: str = HUMAN_MSG,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.system_message = system_message
        self.human_message = human_message

    def select(self, task_name: str, task_description: str) -> list[str]:
        tool_pool = [tool.dict() for tool in self.tools]
        messages = [
            SystemMessagePromptTemplate.from_template(self.system_message),
            HumanMessagePromptTemplate.from_template(self.human_message),
        ]

        chain = ChatPromptTemplate.from_messages(messages) | self.llm

        chain_output = chain.invoke(
            {
                'tool_pool': tool_pool,
                'task_name': task_name,
                'task_description': task_description,
            }
        )

        try:
            all_tool_name = set([tool.tool_name for tool in self.tools])
            output = list(set(eval(chain_output.content)) & all_tool_name)
            return output
        except Exception as e:
            print(e)
            return []
