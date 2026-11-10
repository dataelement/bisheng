"""覆盖 AC: AC-06, AC-07, AC-08, AC-17, AC-19。"""

import pytest

from bisheng.common.errcode.flow import (
    PlatformAgentExecutionError,
    PlatformAgentPublicationError,
    WorkFlowOnlineEditError,
)
from bisheng.core.config.settings import PlatformAgentConf
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.domain.repositories.platform_agent import PlatformAgentRepository
from bisheng.workflow.domain.schemas.platform_agent import PUBLICATION_KEY, VerifiedAgentActor, canonical_digest


def test_publish_conflict_and_rollback_preserve_the_old_published_graph(agent_store):
    repository, sessions, graph, _ = agent_store
    with sessions() as session:
        version = session.get(FlowVersion, 1)
        version.data = {**graph, "changed": True}
        session.add(version)
        session.commit()
    with pytest.raises(PlatformAgentPublicationError):
        repository.publish_validated_graph("f" * 32, 1, canonical_digest(graph), {"nodes": {}})
    assert repository.get_workflow("f" * 32)["data"] == graph
    snapshot = repository.publish_validated_graph(
        "f" * 32, 1, canonical_digest({**graph, "changed": True}), {"nodes": {}}
    )
    assert PUBLICATION_KEY not in snapshot
    with pytest.raises(WorkFlowOnlineEditError):
        repository.save_version(1, data={"nodes": [], "edges": [], "draft": True})
    with sessions() as session:
        flow = session.get(Flow, "f" * 32)
        flow.status = 1
        session.add(flow)
        session.commit()
    repository.save_version(1, data={"nodes": [], "edges": [], "draft": True})
    assert repository.get_workflow("f" * 32)["data"] == snapshot


def test_dispatch_and_call_permissions_are_durable_and_cannot_be_replayed(agent_store):
    repository, sessions, graph, _ = agent_store
    config = PlatformAgentConf(mode="mock")
    execution, dispatch_id = repository.prepare_execution(
        "f" * 32, "session", VerifiedAgentActor(12, 7), graph, config, "DEBUG"
    )
    dispatch = repository.claim_dispatch(execution["execution_id"], dispatch_id)
    assert dispatch is not None
    assert PlatformAgentRepository(sessions).claim_dispatch(dispatch.execution_id, dispatch_id) is None
    repository.reserve_call(dispatch, "node", 0, "a" * 64, {"agent_id": "fixture", "version_id": "v1"}, 1005)
    with pytest.raises(PlatformAgentExecutionError):
        repository.reserve_call(dispatch, "node", 0, "a" * 64, {}, 1005)
    repository.request_stop(dispatch.execution_id)
    with pytest.raises(PlatformAgentExecutionError):
        with repository.output_scope(dispatch, "node", 0, config):
            raise AssertionError("a stopped execution must not commit output")


def test_sql_snapshot_survives_edits_and_failed_output_commit(agent_store):
    repository, _, graph, now = agent_store
    config = PlatformAgentConf(mode="mock")
    execution, dispatch_id = repository.prepare_execution(
        "f" * 32, "session", VerifiedAgentActor(12, 7), graph, config, "DEBUG"
    )
    graph["changed-after-admission"] = True
    dispatch = repository.claim_dispatch(execution["execution_id"], dispatch_id)
    assert "changed-after-admission" not in repository.get_execution(dispatch.execution_id)["graph_snapshot"]
    repository.reserve_call(dispatch, "node", 0, "a" * 64, {}, 1005)
    with pytest.raises(RuntimeError):
        with repository.output_scope(dispatch, "node", 0, config):
            raise RuntimeError("variable write failed")
    assert repository.get_execution(dispatch.execution_id)["calls"]["node:0"]["state"] == "DISPATCHING"
    with repository.output_scope(dispatch, "node", 0, config):
        pass
    assert repository.get_execution(dispatch.execution_id)["calls"]["node:0"]["state"] == "SUCCEEDED"
    now[0] = 1006
    repository.reserve_call(dispatch, "node", 1, "b" * 64, {}, 1007)
    now[0] = 1008
    with pytest.raises(PlatformAgentExecutionError):
        with repository.output_scope(dispatch, "node", 1, config):
            raise AssertionError("expired output")
