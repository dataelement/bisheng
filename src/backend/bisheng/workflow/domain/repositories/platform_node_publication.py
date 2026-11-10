"""两类平台节点共用的原子发布写入。"""

from copy import deepcopy

from sqlmodel import select

from bisheng.common.errcode.flow import PlatformAgentPublicationError
from bisheng.database.models.flow import FlowStatus
from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.domain.schemas.platform_agent import PUBLICATION_KEY, canonical_digest
from bisheng.workflow.domain.schemas.platform_knowledge import PUBLICATION_KEY as KNOWLEDGE_KEY


class PlatformNodePublication:
    @staticmethod
    def candidate_graph(graph):
        result = deepcopy(graph or {})
        result.pop(PUBLICATION_KEY, None)
        result.pop(KNOWLEDGE_KEY, None)
        return result

    def publish_validated_graph(self, flow_id, version_id, expected_digest, binding, *, knowledge_binding=None):
        with self.transaction() as session:
            flow = self._flow(session, flow_id, lock=True)
            version = self._version(session, version_id, lock=True)
            graph = self.candidate_graph(version.data)
            if version.flow_id != flow_id or canonical_digest(graph) != expected_digest:
                raise PlatformAgentPublicationError()
            return self.write_publication(session, flow, version, graph, binding, knowledge_binding)

    @staticmethod
    def write_publication(session, flow, version, graph, binding, knowledge_binding):
        if binding.get("nodes"):
            graph[PUBLICATION_KEY] = deepcopy(binding)
        if knowledge_binding and knowledge_binding.get("nodes"):
            graph[KNOWLEDGE_KEY] = deepcopy(knowledge_binding)
        for item in session.exec(select(FlowVersion).where(FlowVersion.flow_id == flow.id)).all():
            item.is_current = int(item.id == version.id)
            session.add(item)
        version.data = deepcopy(graph)
        flow.data = deepcopy(graph)
        flow.status = FlowStatus.ONLINE.value
        session.add(version)
        session.add(flow)
        return graph
