
from typing import List, Optional

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
    variable_value: Optional[List[str]] = []

    class Config:
        """Configuration for this pydantic object."""

        extra = Extra.forbid

    def text(self):
        if self.variable_value:
            text = {}
            for index, value in enumerate(self.variable_value):
                text[self.variables[index]] = value

            return text
        else:
            return {}


class InputFileNode(BaseModel):
    file_path: Optional[str]
    file_name: Optional[str]
    file_type: Optional[str]  # tips for file
    """Output组件，用来控制输出"""

    def text(self):
        # judge if file_path is oss address
        if not self.file_path:
            return ''
        return [self.file_path, self.file_name]
