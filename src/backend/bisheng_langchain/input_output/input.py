
from typing import List, Optional

from pydantic import ConfigDict, BaseModel


class InputNode(BaseModel):
    """Input组件，用来控制输入"""
    input: Optional[List[str]] = None

    def text(self):
        return self.input


class VariableNode(BaseModel):
    """用来设置变量"""
    # key
    variables: Optional[List[str]] = None
    # vaulues
    variable_value: Optional[List[str]] = []
    model_config = ConfigDict(extra="forbid")

    def text(self):
        if self.variable_value:
            text = {}
            for index, value in enumerate(self.variable_value):
                text[self.variables[index]] = value

            return text
        else:
            return {}


class InputFileNode(BaseModel):
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None  # tips for file
    """Output组件，用来控制输出"""

    def text(self):
        # judge if file_path is oss address
        if not self.file_path:
            return ''
        return [self.file_path, self.file_name]
