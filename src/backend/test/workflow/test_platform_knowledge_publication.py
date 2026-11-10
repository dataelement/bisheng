"""覆盖 AC: AC-09, AC-19。"""

import pytest

from bisheng.common.errcode.flow import PlatformAgentPublicationError
from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.domain.schemas.platform_agent import PUBLICATION_KEY as AGENT_KEY
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest
from bisheng.workflow.domain.schemas.platform_knowledge import PUBLICATION_KEY


def test_combined_publication_commits_both_bindings_or_neither(agent_store):
    repository, sessions, graph, _ = agent_store
    args = ("f" * 32, 1, canonical_digest(graph), {"nodes": {"agent": {}}})
    with sessions() as session:
        version = session.get(FlowVersion, 1)
        version.data = {**graph, "edited": True}
        session.add(version)
        session.commit()
    knowledge = {"nodes": {"retrieve": {}}}
    with pytest.raises(PlatformAgentPublicationError):
        repository.publish_validated_graph(*args, knowledge_binding=knowledge)
    assert repository.get_workflow(args[0])["data"] == graph
    published = repository.publish_validated_graph(
        args[0], 1, canonical_digest({**graph, "edited": True}), args[3], knowledge_binding=knowledge
    )
    assert published[AGENT_KEY] == args[3] and published[PUBLICATION_KEY] == knowledge
    assert repository.get_version(1)["data"] == repository.get_workflow(args[0])["data"] == published
    assert repository.candidate_graph(published) == {**graph, "edited": True}
