
from typing import List, Optional

from pydantic import BaseModel, Extra


class InputNode(BaseModel):
    """Input组件，用来控制输入"""
    input: Optional[List[str]]

    def text(self):
        return self.input


class VariableNode(BaseModel):
    """用来设置变量"""
    variables: Optional[List[str]]

    class Config:
        """Configuration for this pydantic object."""

        extra = Extra.forbid

    def text(self):
        return self.variables


class InputFileNode(BaseModel):
    file_path: Optional[str]
    file_name: Optional[str]
    """Output组件，用来控制输出"""

    def text(self):
        return [self.file_path, self.file_name] if self.file_path else ''
