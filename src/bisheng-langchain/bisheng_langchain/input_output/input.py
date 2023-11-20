
from typing import List

from pydantic import BaseModel


class InputNode(BaseModel):
    """Input组件，用来控制输入"""

    @classmethod
    def initialize(cls, input: List[str] = None):
        return input if input else ''


class VariableNode(BaseModel):

    variables: List[str]

    @classmethod
    def initialize(cls, variables: List[str] = None):
        return variables if variables else ''


class InputFileNode(BaseModel):
    file_path: str
    """Output组件，用来控制输出"""

    def ___init__(self, file_path: str):
        self.file_path = file_path
        super().__init__(file_path=file_path)

    @classmethod
    def initialize(cls, file_path: str = None, file_name: str = None):
        return [file_path, file_name] if file_path else ''
