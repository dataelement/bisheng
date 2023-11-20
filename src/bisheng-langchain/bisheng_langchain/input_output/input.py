
from typing import List

from pydantic import BaseModel


class InputNode(BaseModel):
    """Input组件，用来控制输入"""
    id: str
    target_id: str
    questions: List[str]
    input_key: str

    def __init__(self, id, target_id, questions, input_key):
        self.id = id
        self.target_id = target_id
        self.questions = questions
        self.input_key = input_key

    @classmethod
    def initialize(cls, id: str, target_id: str,
                   input_key: str, question: List[str] = None,):
        cls(id, target_id, question, input_key)

    def text(self):
        return self.questions


class VariableNode(BaseModel):
    variables: List[str]

    @classmethod
    def initialize(cls, variables: List[str] = None):
        return variables if variables else ''


class InputFileNode(BaseModel):
    file_type: str
    file_path: str
    """Output组件，用来控制输出"""

    def ___init__(self, file_path: str, file_type: str):
        self.file_path = file_path
        self.file_type = file_type
        super().__init__(file_path=file_path)

    @classmethod
    def initialize(cls, file_path: str = None, file_name: str = None):
        return [file_path, file_name] if file_path else ''
