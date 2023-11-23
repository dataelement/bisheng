
from typing import List

from pydantic import BaseModel, Extra


class Variable(BaseModel):
    """用来设置变量"""
    variable_name: str
    variable_key: str

    class Config:
        """Configuration for this pydantic object."""

        extra = Extra.forbid

    @classmethod
    def initialize(cls, input: List[str] = None):
        return input if input else ''


class PresetQuestion(BaseModel):
    pass
