from bisheng.workflow.common.node import NodeType
from bisheng.workflow.nodes.agent.agent import AgentNode
from bisheng.workflow.nodes.code.code import CodeNode
from bisheng.workflow.nodes.condition.condition import ConditionNode
from bisheng.workflow.nodes.end.end import EndNode
from bisheng.workflow.nodes.input.input import InputNode
from bisheng.workflow.nodes.llm.llm import LLMNode
from bisheng.workflow.nodes.output.output import OutputNode
from bisheng.workflow.nodes.qa_retriever.qa_retriever import QARetrieverNode
from bisheng.workflow.nodes.rag.rag import RagNode
from bisheng.workflow.nodes.report.report import ReportNode
from bisheng.workflow.nodes.start.start import StartNode
from bisheng.workflow.nodes.tool.tool import ToolNode

NODE_CLASS_MAP = {
    NodeType.START.value: StartNode,
    NodeType.END.value: EndNode,
    NodeType.INPUT.value: InputNode,
    NodeType.OUTPUT.value: OutputNode,
    NodeType.TOOL.value: ToolNode,
    NodeType.RAG.value: RagNode,
    NodeType.REPORT.value: ReportNode,
    NodeType.QA_RETRIEVER.value: QARetrieverNode,
    NodeType.CONDITION.value: ConditionNode,
    NodeType.AGENT.value: AgentNode,
    NodeType.CODE.value: CodeNode,
    NodeType.LLM.value: LLMNode
}


class NodeFactory:
    @classmethod
    def get_node_class(cls, node_type: str) -> 'BaseNode':
        return NODE_CLASS_MAP.get(node_type)

    @classmethod
    def instance_node(cls, node_type: str, **kwargs) -> 'BaseNode':
        node_class = cls.get_node_class(node_type)
        if node_class is None:
            raise Exception(f'未知的节点类型：{node_type}')
        return node_class(**kwargs)
