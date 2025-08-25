import itertools
import os
import sys
from typing import List, Type

from langchain_community.tools import Tool
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool

from bisheng_langchain.gpts.tools.code_interpreter.e2b_executor import E2bCodeExecutor
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor

CODE_BLOCK_PATTERN = r"```(\w*)\n(.*?)\n```"
DEFAULT_TIMEOUT = 600
WIN32 = sys.platform == 'win32'
PATH_SEPARATOR = WIN32 and '\\' or '/'
WORKING_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'extensions')
TIMEOUT_MSG = 'Timeout'
UNKNOWN = "unknown"


def infer_lang(code):
    """infer the language for the code.
    TODO: make it robust.
    """
    if code.startswith("python ") or code.startswith("pip") or code.startswith("python3 "):
        return "sh"

    # check if code is a valid python code
    try:
        compile(code, "test", "exec")
        return "python"
    except SyntaxError:
        # not a valid python code
        return UNKNOWN


def head_file(path: str, n: int) -> List[str]:
    """Get the first n lines of a file."""
    try:
        with open(path, 'r') as f:
            return [str(line) for line in itertools.islice(f, n)]
    except Exception:
        return []


class CodeInterpreterToolArguments(BaseModel):
    """Arguments for the BearlyInterpreterTool."""

    python_code: str = Field(
        ...,
        examples=["print('Hello World')"],
        description=(
            'The pure python script to be evaluated. '
            'The contents will be in main.py. '
            'It should not be in markdown format.'
        ),
    )


class CodeInterpreterTool(BaseTool):
    """Tool for evaluating python code in native environment."""

    name = 'bisheng_code_interpreter'
    args_schema: Type[BaseModel] = CodeInterpreterToolArguments

    def __init__(
            self,
            executor_type: str = 'local',
            **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.executor_type = executor_type
        if self.executor_type == 'local':
            self.executor = LocalExecutor(**kwargs)
        else:
            self.executor = E2bCodeExecutor(**kwargs)

    @property
    def description(self) -> str:
        return self.executor.description

    def _run(self, python_code: str) -> dict:
        return self.executor.run(python_code)

    def close(self) -> None:
        self.executor.close()
