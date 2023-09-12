from typing import Callable, List, Optional

from bisheng.interface.importing.utils import get_function
from bisheng.utils import validate
from langchain.agents.tools import Tool
from langchain.schema.output import Generation
from pydantic import BaseModel, validator


class Input(BaseModel):
    """Input组件，用来控制输入"""
    @classmethod
    def initialize(cls, input: List[str] = None):
        return input if input else ''

class Output(BaseModel):
    """Output组件，用来控制输出"""

    @classmethod
    def initialize(cls, file_path:str = None):
        return file_path if file_path else ''

class InputFile(BaseModel):
    file_path:str
    """Output组件，用来控制输出"""
    def ___init__(self, file_path:str):
        self.file_path = file_path
        super().__init__(file_path = file_path)

    @classmethod
    def initialize(cls, file_path:str = None):
        return file_path if file_path else ''

CUSTOM_INPUTOUTPUT = {
    'InputNode': Input,
    'OutputNode': Output,
    'InputFileNode': InputFile,
}
