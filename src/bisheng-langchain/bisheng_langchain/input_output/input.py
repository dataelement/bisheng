
from typing import List

from pydantic import BaseModel


class InputNode(BaseModel):
    """Input组件，用来控制输入"""
    input: List[str]

    def text(self):
        return self.input


class VariableNode(BaseModel):
    variables: List[str]

    def text(self):
        return self.variables


class InputFileNode(BaseModel):
    file_type: str
    file_path: str
    file_name: str
    """Output组件，用来控制输出"""

    def text(self):
        return [self.file_path, self.file_name] if self.file_path else ''
