from enum import Enum
from typing import Optional, Any

from pydantic import BaseModel, Field


class NodeType(Enum):
    """ 节点类型 """
    START = "start"
    END = "end"
    INPUT = "input"
    AGENT = "agent"
    CODE = "code"
    CONDITION = "condition"
    LLM = "llm"
    OUTPUT = "output"
    QA_RETRIEVER = "qa_retriever"
    RAG = "rag"
    REPORT = "report"
    TOOL = "tool"


class BaseNodeData(BaseModel):
    pass
