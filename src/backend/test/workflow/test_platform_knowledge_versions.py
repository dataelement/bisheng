"""覆盖 AC: AC-09, AC-19。已发布图与后续草稿分别存储。"""

import pytest

from bisheng.common.errcode.flow import WorkFlowOnlineEditError
from bisheng.database.models.flow import Flow
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest
from bisheng.workflow.domain.schemas.platform_knowledge import PUBLICATION_KEY


def test_draft_does_not_replace_or_copy_the_published_binding(agent_store):
    repo, sessions, graph, _ = agent_store
    flow_id = "f" * 32
    published = repo.publish_validated_graph(
        flow_id,
        1,
        canonical_digest(graph),
        {},
        knowledge_binding={"nodes": {"retrieve": {"top_k": 5}}},
    )
    with pytest.raises(WorkFlowOnlineEditError):
        repo.save_version(1, data={**graph, "changed": True})
    with sessions() as session:
        flow = session.get(Flow, flow_id)
        flow.status = 1
        session.add(flow)
        session.commit()
    draft = repo.save_version(1, data={**published, "changed": True})
    assert PUBLICATION_KEY not in draft["data"]
    assert repo.get_workflow(flow_id)["data"] == published
