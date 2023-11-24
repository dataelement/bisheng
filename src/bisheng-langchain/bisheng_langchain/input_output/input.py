
from typing import Dict, List, Optional

from pydantic import BaseModel, Extra


class InputNode(BaseModel):
    """Input组件，用来控制输入"""
    input: Optional[List[str]]

    def text(self):
        return self.input


class VariableNode(BaseModel):
    """用来设置变量"""
    # key
    variables: Optional[List[str]]
    # vaulues
    variable_value: Optional[List[Dict]]

    class Config:
        """Configuration for this pydantic object."""

        extra = Extra.forbid

    def text(self):
        return self.variable_value


class InputFileNode(BaseModel):
    file_path: Optional[str]
    file_name: Optional[str]
    file_type: Optional[str]  # tips for file
    """Output组件，用来控制输出"""

    def text(self):
        return [self.file_path, self.file_name] if self.file_path else ''
