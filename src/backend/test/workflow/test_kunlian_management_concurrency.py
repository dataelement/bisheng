"""Formal routes must not fall back to browser last-write-wins behavior."""

from types import SimpleNamespace

import pytest

from bisheng.common.errcode.flow import WorkflowRegistrationConflict
from bisheng.database.models.flow import Flow, FlowStatus
from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.domain.repositories.kunlian_registration import version_revision
from bisheng.workflow.domain.repositories.kunlian_workflow_api import KunlianWorkflowMetadataRepository
from test.workflow.test_kunlian_workflow_publication import FLOW_ID, seed


def test_formal_save_rejects_stale_revision_and_preserves_new_data(registration_store):
    seed(registration_store)
    repo = KunlianWorkflowMetadataRepository(sessions=registration_store.sessions)
    with registration_store.transaction() as session:
        revision = version_revision(session.get(FlowVersion, 1))
    updated = repo.save_draft(FLOW_ID, 7, 1, revision, name="new")
    assert updated["name"] == "new"
    assert updated["draft_revision"] != revision
    with pytest.raises(WorkflowRegistrationConflict):
        repo.save_draft(FLOW_ID, 7, 1, revision, name="stale")
    with registration_store.transaction() as session:
        assert session.get(FlowVersion, 1).name == "new"
        flow, version = session.get(Flow, FLOW_ID), session.get(FlowVersion, 1)
        flow.status, version.is_current = FlowStatus.ONLINE.value, 1
        revision = version_revision(version)
    with pytest.raises(WorkflowRegistrationConflict):
        repo.save_draft(FLOW_ID, 7, 1, revision, name="online")


def test_formal_unpublish_rejects_stale_current_version(registration_store):
    seed(registration_store)
    repo = KunlianWorkflowMetadataRepository(sessions=registration_store.sessions)
    with registration_store.transaction() as session:
        session.get(Flow, FLOW_ID).status = FlowStatus.ONLINE.value
        session.get(FlowVersion, 2).is_current = 1
    with pytest.raises(WorkflowRegistrationConflict):
        repo.unpublish(FLOW_ID, 7, 1)
    with registration_store.transaction() as session:
        assert session.get(Flow, FLOW_ID).status == FlowStatus.ONLINE.value
    repo.unpublish(FLOW_ID, 7, 2)
    repo.unpublish(FLOW_ID, 7, 2)
    with registration_store.transaction() as session:
        assert session.get(Flow, FLOW_ID).status == FlowStatus.OFFLINE.value


async def test_formal_application_uses_locked_repository_not_browser_save(monkeypatch):
    from bisheng.workflow.application import kunlian_workflow_api as api

    async def allow(*args, **kwargs):
        return None

    monkeypatch.setattr(api, "require_business_action", allow)
    calls = []

    class Repository:
        def save_draft(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"draft_revision": "new"}

        def unpublish(self, *args):
            calls.append(args)

    monkeypatch.setattr(
        "bisheng.workflow.domain.repositories.kunlian_workflow_api.KunlianWorkflowMetadataRepository", Repository
    )
    service = api.KunlianWorkflowApi(flow_service=SimpleNamespace(), workflow_service=SimpleNamespace())

    async def version(*args):
        return {}

    service._version = version
    user = SimpleNamespace(tenant_id=7, user_id=11)
    request = SimpleNamespace(headers={"If-Match": "revision"})
    result = await service.save_version(
        user, request, FLOW_ID, 1, SimpleNamespace(name="new", description=None, data=None)
    )
    assert result["draft_revision"] == "new"
    assert calls[0][0] == (FLOW_ID, 7, 1, "revision")
    await service.publish(user, FLOW_ID, 1, online=False)
    assert calls[-1] == (FLOW_ID, 7, 1)
