from enum import Enum


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


