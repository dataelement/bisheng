from typing import Dict, Generator, List, Type, Union

from bisheng.graph.edge.base import Edge
from bisheng.graph.graph.constants import lazy_load_vertex_dict
from bisheng.graph.utils import process_flow
from bisheng.graph.vertex.base import Vertex
from bisheng.graph.vertex.types import FileToolVertex, LLMVertex, ToolkitVertex
from bisheng.interface.tools.constants import FILE_TOOLS
from bisheng.utils import payload
from langchain.chains.base import Chain
from loguru import logger


class Graph:
    """A class representing a graph of nodes and edges."""

    def __init__(
        self,
        nodes: List[Dict[str, Union[str, Dict[str, Union[str, List[str]]]]]],
        edges: List[Dict[str, str]],
    ) -> None:
        self._vertices = nodes
        self._nodes = nodes
        self._edges = edges
        self.raw_graph_data = {'nodes': nodes, 'edges': edges}
        self.top_level_vertices = []
        for vertex in self._vertices:
            if vertex_id := vertex.get('id'):
                self.top_level_vertices.append(vertex_id)
        self._graph_data = process_flow(self.raw_graph_data)

        self._vertices = self._graph_data['nodes']
        self._edges = self._graph_data['edges']
        self._build_graph()

    def __getstate__(self):
        return self.raw_graph_data

    def __setstate__(self, state):
        self.__init__(**state)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Graph):
            return False
        return self.__repr__() == other.__repr__()

    @classmethod
    def from_payload(cls, payload: Dict) -> 'Graph':
        """
        Creates a graph from a payload.

        Args:
            payload (Dict): The payload to create the graph from.˜`

        Returns:
            Graph: The created graph.
        """
        if 'data' in payload:
            payload = payload['data']
        try:
            nodes = payload['nodes']
            edges = payload['edges']
            return cls(nodes, edges)
        except KeyError as exc:
            raise ValueError(
                f"Invalid payload. Expected keys 'nodes' and 'edges'. Found {list(payload.keys())}"
            ) from exc

    def _build_graph(self) -> None:
        """Builds the graph from the nodes and edges."""
        self.vertices = self._build_vertices()
        self.vertex_map = {vertex.id: vertex for vertex in self.vertices}
        self.edges = self._build_edges()

        # This is a hack to make sure that the LLM node is sent to
        # the toolkit node
        self._build_vertex_params()
        # remove invalid vertices
        self._validate_vertices()

    def _build_vertex_params(self) -> None:
        """Identifies and handles the LLM vertex within the graph."""
        llm_vertex = None
        for vertex in self.vertices:
            vertex._build_params()
            if isinstance(vertex, LLMVertex):
                llm_vertex = vertex

        if llm_vertex:
            for vertex in self.vertices:
                if isinstance(vertex, ToolkitVertex):
                    vertex.params['llm'] = llm_vertex

    def _validate_vertices(self) -> None:
        """Check that all vertices have edges"""
        if len(self.vertices) == 1:
            return
        for vertex in self.vertices:
            if not self._validate_vertex(vertex):
                raise ValueError(f'{vertex.vertex_type} is not connected to any other components')

    def _validate_vertex(self, vertex: Vertex) -> bool:
        """Validates a vertex."""
        # All vertices that do not have edges are invalid
        return len(self.get_vertex_edges(vertex.id)) > 0

    def get_vertex(self, vertex_id: str) -> Union[None, Vertex]:
        """Returns a vertex by id."""
        return self.vertex_map.get(vertex_id)

    def get_vertex_edges(self, vertex_id: str) -> List[Edge]:
        """Returns a list of edges for a given vertex."""
        return [
            edge for edge in self.edges
            if edge.source_id == vertex_id or edge.target_id == vertex_id
        ]

    def get_vertices_with_target(self, vertex_id: str) -> List[Vertex]:
        """Returns the vertices connected to a vertex."""
        vertices: List[Vertex] = []
        for edge in self.edges:
            if edge.target_id == vertex_id:
                vertex = self.get_vertex(edge.source_id)
                if vertex is None:
                    continue
                vertices.append(vertex)
        return vertices

    def get_input_nodes(self) -> List[Vertex]:
        """Builds the graph."""
        # Get root node
        input_node = payload.get_root_node(self)
        if input_node is None:
            raise ValueError('No input root node found')
        return input_node

    async def abuild(self) -> Chain:
        """Builds the graph."""
        # Get root node
        root_vertex = payload.get_root_vertex(self)
        if root_vertex is None:
            raise ValueError('No root node vertex found')

        return await root_vertex.build()

    def topological_sort(self) -> List[Vertex]:
        """
        Performs a topological sort of the vertices in the graph.

        Returns:
            List[Vertex]: A list of vertices in topological order.

        Raises:
            ValueError: If the graph contains a cycle.
        """
        # States: 0 = unvisited, 1 = visiting, 2 = visited
        state = {node: 0 for node in self.vertices}
        sorted_vertices = []

        def dfs(node):
            if state[node] == 1:
                # We have a cycle
                raise ValueError('Graph contains a cycle, cannot perform topological sort')
            if state[node] == 0:
                state[node] = 1
                for edge in node.edges:
                    if edge.source_id == node.id:
                        dfs(self.get_vertex(edge.target_id))
                state[node] = 2
                sorted_vertices.append(node)

        # Visit each node
        for node in self.vertices:
            if state[node] == 0:
                dfs(node)

        return list(reversed(sorted_vertices))

    def generator_build(self) -> Generator:
        """Builds each vertex in the graph and yields it."""
        sorted_vertices = self.topological_sort()
        logger.debug('There are %s vertices in the graph', len(sorted_vertices))
        yield from sorted_vertices

    def get_vertex_neighbors(self, vertex: Vertex) -> Dict[Vertex, int]:
        """Returns the neighbors of a vertex."""
        neighbors: Dict[Vertex, int] = {}
        for edge in self.edges:
            if edge.source_id == vertex.id:
                neighbor = self.get_vertex(edge.target_id)
                if neighbor is None:
                    continue
                if neighbor not in neighbors:
                    neighbors[neighbor] = 0
                neighbors[neighbor] += 1
            elif edge.target_id == vertex.id:
                neighbor = self.get_vertex(edge.source_id)
                if neighbor is None:
                    continue
                if neighbor not in neighbors:
                    neighbors[neighbor] = 0
                neighbors[neighbor] += 1
        return neighbors

    def _build_edges(self) -> List[Edge]:
        """Builds the edges of the graph."""
        # Edge takes two nodes as arguments, so we need to build the nodes first
        # and then build the edges
        # if we can't find a node, we raise an error

        edges: List[Edge] = []
        for edge in self._edges:
            source = self.get_vertex(edge['source'])
            target = self.get_vertex(edge['target'])
            if source is None:
                raise ValueError(f"Source node {edge['source']} not found")
            if target is None:
                raise ValueError(f"Target node {edge['target']} not found")
            edges.append(Edge(source, target, edge))
        return edges

    def _get_vertex_class(self, node_type: str, vertex_base_type: str) -> Type[Vertex]:
        """Returns the node class based on the node type."""
        if node_type in FILE_TOOLS:
            return FileToolVertex
        if vertex_base_type == 'CustomComponent':
            return lazy_load_vertex_dict.get_custom_component_vertex_type()
        if vertex_base_type in lazy_load_vertex_dict.VERTEX_TYPE_MAP:
            return lazy_load_vertex_dict.VERTEX_TYPE_MAP[vertex_base_type]
        return (lazy_load_vertex_dict.VERTEX_TYPE_MAP[node_type]
                if node_type in lazy_load_vertex_dict.VERTEX_TYPE_MAP else Vertex)

    def _build_vertices(self) -> List[Vertex]:
        """Builds the vertices of the graph."""
        nodes: List[Vertex] = []
        for node in self._vertices:
            node_data = node['data']
            node_type: str = node_data['type']  # type: ignore
            vertex_base_type: str = node_data['node']['template']['_type']  # type: ignore

            VertexClass = self._get_vertex_class(node_type, vertex_base_type)
            vertex_instance = VertexClass(node, graph=self)
            vertex_instance.set_top_level(self.top_level_vertices)
            nodes.append(vertex_instance)

        return nodes

    def get_children_by_node_type(self, node: Vertex, node_type: str) -> List[Vertex]:
        """Returns the children of a node based on the node type."""
        children = []
        node_types = [node.data['type']]
        if 'node' in node.data:
            node_types += node.data['node']['base_classes']
        if node_type in node_types:
            children.append(node)
        return children

    def __repr__(self):
        node_ids = [node.id for node in self.vertices]
        edges_repr = '\n'.join([f'{edge.source_id} --> {edge.target_id}' for edge in self.edges])
        return f'Graph:\nNodes: {node_ids}\nConnections:\n{edges_repr}'
