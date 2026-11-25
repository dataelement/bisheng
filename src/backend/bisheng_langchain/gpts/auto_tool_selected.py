import ast
import json

from langchain_classic.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_core.language_models.base import LanguageModelLike
from loguru import logger
from pydantic import BaseModel

from bisheng_langchain.gpts.prompts.select_tools_prompt import HUMAN_MSG, SYS_MSG

_MAX_SELECTION_LENGTH = 16384
_MAX_SELECTED_TOOLS = 256
_MAX_TOOL_NAME_LENGTH = 256


def _parse_tool_names(content: str) -> list[str]:
    if not isinstance(content, str) or len(content) > _MAX_SELECTION_LENGTH:
        raise ValueError("Tool selection exceeds length limit")
    try:
        names = json.loads(content)
    except json.JSONDecodeError:
        # The shipped prompt explicitly requests ['tool1', 'tool2']; support that
        # literal format without interpreting Python expressions or callables.
        tree = ast.parse(content.strip(), mode="eval")
        if not isinstance(tree.body, ast.List) or len(tree.body.elts) > _MAX_SELECTED_TOOLS:
            raise ValueError("Tool selection must be a string list")
        if any(not isinstance(item, ast.Constant) or type(item.value) is not str for item in tree.body.elts):  # noqa: E721  # exact type, bool must not pass as int
            raise ValueError("Tool selection must contain only literal strings")
        names = ast.literal_eval(tree)
    if type(names) is not list or len(names) > _MAX_SELECTED_TOOLS:  # noqa: E721  # exact type, bool must not pass as int
        raise ValueError("Tool selection must be a bounded string list")
    if any(type(name) is not str or len(name) > _MAX_TOOL_NAME_LENGTH for name in names):  # noqa: E721  # exact type, bool must not pass as int
        raise ValueError("Tool selection must contain only bounded strings")
    return names


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
        tool_pool = [tool.model_dump() for tool in self.tools]
        messages = [
            SystemMessagePromptTemplate.from_template(self.system_message),
            HumanMessagePromptTemplate.from_template(self.human_message),
        ]

        chain = ChatPromptTemplate.from_messages(messages) | self.llm

        chain_output = chain.invoke(
            {
                "tool_pool": tool_pool,
                "task_name": task_name,
                "task_description": task_description,
            }
        )

        try:
            names = _parse_tool_names(chain_output.content)
        except (ValueError, SyntaxError, RecursionError):
            # Preserve the existing fail-closed empty selection on invalid model
            # output; do not log the untrusted payload or provider secrets.
            logger.warning("Rejected malformed assistant tool selection")
            return []
        all_tool_names = {tool.tool_name for tool in self.tools}
        return list(dict.fromkeys(name for name in names if name in all_tool_names))
