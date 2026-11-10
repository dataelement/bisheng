from types import SimpleNamespace

import pytest

from bisheng.common.errcode.flow import WorkflowRegistrationConflict
from bisheng.core.config.settings import WorkflowRegistrationConf
from bisheng.database.models.flow import Flow, FlowStatus
from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.domain.schemas.kunlian_registration import RegistrationScope

SCOPE = RegistrationScope(7, "mock", 1)
FLOW_ID = "f" * 32
GRAPH = {
    "nodes": [
        {
            "data": {
                "id": "out",
                "type": "output",
                "group_params": [
                    {"params": [{"key": "message", "value": {"msg": "private", "files": []}}]},
                ],
            }
        }
    ],
    "edges": [],
}


def seed(repo, workflow_id=FLOW_ID, versions=(1, 2)):
    with repo.transaction() as session:
        session.add(Flow(id=workflow_id, tenant_id=7, user_id=11, name="flow"))
        for index in versions:
            session.add(FlowVersion(id=index, flow_id=workflow_id, tenant_id=7, name=f"v{index}", data=GRAPH))


def publish(repo, version, workflow_id=FLOW_ID):
    from bisheng.workflow.domain.services.kunlian_descriptor import prepare_descriptor

    flow, candidate, revision = repo.candidate(SCOPE, workflow_id, version)
    material = prepare_descriptor(flow, candidate, GRAPH, {}, {})
    return repo.publish(SCOPE, workflow_id, version, revision, material, {}, {})


def test_publication_versions_and_withdrawal_are_atomic(registration_store):
    repo = registration_store
    seed(repo)
    first = publish(repo, 1)
    with pytest.raises(WorkflowRegistrationConflict):
        repo.publish(SCOPE, FLOW_ID, 2, "stale", None, {}, {})
    assert repo.highwater(SCOPE) == first["sequence"] == 1
    second = publish(repo, 2)
    assert second["retired_version_id"] == "1"
    assert repo.version(SCOPE, FLOW_ID, 1)["availability"] == "REPLACED"
    assert "private" not in str(repo.version(SCOPE, FLOW_ID, 2)["descriptor"])
    with pytest.raises(WorkflowRegistrationConflict):
        repo.unpublish(SCOPE, FLOW_ID, 1)
    offline = repo.unpublish(SCOPE, FLOW_ID, 2)
    assert offline["sequence"] == 3
    assert repo.version(SCOPE, FLOW_ID, 2)["availability"] == "OFFLINE"
    assert publish(repo, 2)["sequence"] == 4


def test_failed_event_write_rolls_back_workflow_publication(registration_store, monkeypatch):
    repo = registration_store
    seed(repo)

    def fail(*_):
        raise RuntimeError("fail before commit")

    monkeypatch.setattr(repo, "_append", fail)
    with pytest.raises(RuntimeError, match="fail before commit"):
        publish(repo, 1)
    with repo.transaction() as session:
        assert session.get(Flow, FLOW_ID).status == 1
        assert not session.get(FlowVersion, 1).is_current
    assert repo.highwater(SCOPE) == 0


def test_offline_rejects_stale_version_of_existing_online_workflow(registration_store):
    repo = registration_store
    seed(repo)
    with repo.transaction() as session:
        session.get(Flow, FLOW_ID).status = FlowStatus.ONLINE.value
        session.get(FlowVersion, 2).is_current = 1

    with pytest.raises(WorkflowRegistrationConflict):
        repo.unpublish(SCOPE, FLOW_ID, 1)

    with repo.transaction() as session:
        assert session.get(Flow, FLOW_ID).status == FlowStatus.ONLINE.value
    assert repo.unpublish(SCOPE, FLOW_ID, 2) is None
    assert repo.highwater(SCOPE) == 0


async def test_publication_rechecks_registration_scope_at_commit(registration_store, monkeypatch):
    from bisheng.workflow.application import kunlian_workflow_management as management
    from bisheng.workflow.application.kunlian_registration import publish_registered

    repo = registration_store
    seed(repo)
    config = WorkflowRegistrationConf(
        mode="mock", tenant_ids={SCOPE.tenant_id}, connection_id=SCOPE.connection_id, workflow_ids={FLOW_ID}
    )
    monkeypatch.setattr(management, "settings", SimpleNamespace(kunlian_workflow_registration=config))
    commit_publication = repo.publish

    def withdraw_enrollment(*args, **kwargs):
        config.workflow_ids.clear()
        return commit_publication(*args, **kwargs)

    monkeypatch.setattr(repo, "publish", withdraw_enrollment)
    with pytest.raises(WorkflowRegistrationConflict):
        await publish_registered(repo, None, SCOPE, FLOW_ID, 1, lambda *_: None)

    assert repo.highwater(SCOPE) == 0
    with repo.transaction() as session:
        assert session.get(Flow, FLOW_ID).status == FlowStatus.OFFLINE.value
