from typing import Optional, List, Any

from pydantic import BaseModel, Field


class EdgeBase(BaseModel):
    id: str = Field(..., description="Unique id for edge")

    source: str = Field(..., description="source node id")
    sourceHandle: str = Field(..., description="source node handle")
    sourceType: Optional[str] = Field("", description="source node type")

    target: str = Field(..., description="target node id")
    targetHandle: str = Field(..., description="target node handle")
    targetType: Optional[str] = Field("", description="target node type")


class EdgeManage:

    def __init__(self, edges: List[Any]):
        self.edges: List[EdgeBase] = [EdgeBase(**one) for one in edges]

        # source: [edges]
        self.source_map = {}
        # target: [edges]
        self.target_map = {}
        for one in self.edges:
            if one.source not in self.source_map:
                self.source_map[one.source] = []
            self.source_map[one.source].append(one)

            if one.target not in self.target_map:
                self.target_map[one.target] = []
            self.target_map[one.target].append(one)

    def get_target_node(self, source: str) -> List[str] | None:
        """ get target node id by source node id"""
        if source not in self.source_map:
            return None
        return [one.target for one in self.source_map[source]]

    def get_source_node(self, target: str) -> List[str] | None:
        """ get source node id by target node id"""
        if target not in self.target_map:
            return None
        return [one.source for one in self.target_map[target]]

    def get_source_edges(self, target: str) -> List[EdgeBase] | None:
        """ get source edges by target node id"""
        if target not in self.target_map:
            return None
        return self.target_map[target]

    def get_target_edges(self, source: str) -> List[EdgeBase] | None:
        """ get target edges by source node id"""
        if source not in self.source_map:
            return None
        return self.source_map[source]

    def get_next_nodes(self, node_id: str, exclude: Optional[List[str]] = None) -> List[str] | None:
        """ get all next nodes by node id"""
        # 获取直接的下游节点
        output_nodes = self.get_target_node(node_id)
        # 排除自己
        if node_id in output_nodes:
            output_nodes.remove(node_id)

        # 排除指定的节点
        if exclude:
            for one in exclude:
                if one in output_nodes:
                    output_nodes.remove(one)

        for one in output_nodes:
            next_nodes = self.get_next_nodes(one, exclude=exclude)
            if next_nodes:
                output_nodes.extend(next_nodes)

        return output_nodes
