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

    def get_all_edges_nodes(self, start_node_id: str, end_node_id: str) -> List[List[str]]:
        """ get all branch nodes from start node to end node """
        branches = []
        def get_node_branch(node_id, branch: List, node_map: dict):
            # 已经遍历过的节点不再遍历，说明成环了
            if node_id in node_map or node_id == end_node_id:
                branches.append(branch)
                return branch
            branch.append(node_id)
            node_map[node_id] = True
            next_nodes = self.get_target_node(node_id)
            if not next_nodes:
                branches.append(branch)
                return branch

            for one_node in next_nodes:
                tmp_node_map = node_map.copy()
                tmp_branch = branch.copy()
                get_node_branch(one_node, tmp_branch, tmp_node_map)
            return branch
        get_node_branch(start_node_id, [], {})
        return branches

    def get_next_nodes(self, node_id: str, exclude: Optional[List[str]] = None) -> List[str] | None:
        """ get all next nodes by node id"""
        # 获取直接的下游节点
        output_nodes = self.get_target_node(node_id)
        if not output_nodes:
            return []
        if not exclude:
            exclude = [node_id]

        # 排除指定的节点
        for one in exclude:
            if one in output_nodes:
                output_nodes.remove(one)

        exclude.extend(output_nodes)
        for one in output_nodes:
            next_nodes = self.get_next_nodes(one, exclude=exclude)
            if next_nodes:
                output_nodes.extend(next_nodes)

        return output_nodes
