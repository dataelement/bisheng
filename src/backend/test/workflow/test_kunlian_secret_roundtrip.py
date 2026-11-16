"""SQLite round-trip evidence only; not MySQL/DM8 concurrency evidence."""

from copy import deepcopy
from importlib import import_module

import pytest

from bisheng.common.errcode.flow import WorkflowRegistrationConflict
from bisheng.database.models.flow import Flow, FlowStatus
from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.domain.repositories.kunlian_registration import version_revision
from bisheng.workflow.domain.repositories.kunlian_workflow_api import KunlianWorkflowMetadataRepository
from bisheng.workflow.domain.schemas.kunlian_redaction import redact_workflow_response
from test.workflow.test_kunlian_workflow_publication import FLOW_ID, seed


def graph(node_id="sql-node", password="stored-secret"):
    value = {"db_name": "reports", "open": True}
    if password is not None:
        value["db_password"] = password
    return {
        "nodes": [
            {
                "id": node_id,
                "data": {
                    "id": node_id,
                    "type": "agent",
                    "group_params": [{"params": [{"key": "sql_agent", "value": value}]}],
                },
            }
        ],
        "edges": [],
    }


def password(data):
    return data["nodes"][0]["data"]["group_params"][0]["params"][0]["value"].get("db_password")


def test_sqlite_read_redacted_then_save_retains_secret(registration_store):
    seed(registration_store)
    repository = KunlianWorkflowMetadataRepository(sessions=registration_store.sessions)
    with registration_store.transaction() as session:
        version = session.get(FlowVersion, 1)
        version.data = graph()
    with registration_store.transaction() as session:
        version = session.get(FlowVersion, 1)
        response = redact_workflow_response({**version.model_dump(), "draft_revision": version_revision(version)})
    assert "stored-secret" not in str(response)
    result = repository.save_draft(FLOW_ID, 7, 1, response["draft_revision"], data=response["data"])
    assert "stored-secret" not in str(redact_workflow_response(result))
    with registration_store.transaction() as session:
        assert password(session.get(FlowVersion, 1).data) == "stored-secret"


@pytest.mark.parametrize(
    "node_id,new_password,expected",
    [("different", None, None), ("sql-node", "replacement", "replacement"), ("sql-node", "", "")],
)
def test_secret_merge_never_moves_secret_or_overrides_explicit_input(node_id, new_password, expected):
    module = import_module("bisheng.workflow.domain.schemas.kunlian_redaction")
    assert hasattr(module, "merge_redacted_workflow_secrets"), "secret roundtrip helper missing"
    incoming, stored = graph(node_id, new_password), graph()
    before = deepcopy(incoming)
    merged = module.merge_redacted_workflow_secrets(incoming, stored)
    assert password(merged) == expected
    assert incoming == before


async def test_nonmock_version_read_supplies_revision_for_save_and_stale_rejection(registration_store, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bisheng.common.schemas.api import resp_200
    from bisheng.workflow.application import kunlian_workflow_api as module

    seed(registration_store)
    with registration_store.transaction() as session:
        version = session.get(FlowVersion, 1)
        version.data = graph()
    with registration_store.transaction() as session:
        raw = session.get(FlowVersion, 1).model_dump()
    monkeypatch.setattr(module, "require_business_action", AsyncMock())
    service = module.KunlianWorkflowApi(flow_service=SimpleNamespace(get_version_info=AsyncMock(return_value=resp_200(raw))))
    service._version = AsyncMock(return_value=raw)
    response = await service.version(SimpleNamespace(user_id=11, tenant_id=7), FLOW_ID, 1)
    assert response.data["draft_revision"] == version_revision(SimpleNamespace(**raw))
    repository = KunlianWorkflowMetadataRepository(sessions=registration_store.sessions)
    updated = repository.save_draft(FLOW_ID, 7, 1, response.data["draft_revision"], name="changed", data=response.data["data"])
    assert "stored-secret" not in str(redact_workflow_response(updated))
    with pytest.raises(WorkflowRegistrationConflict):
        repository.save_draft(FLOW_ID, 7, 1, response.data["draft_revision"], name="stale")


def test_online_metadata_update_rejected_and_unchanged(registration_store):
    seed(registration_store)
    with registration_store.transaction() as session:
        session.get(Flow, FLOW_ID).status = FlowStatus.ONLINE.value
    repository = KunlianWorkflowMetadataRepository(sessions=registration_store.sessions)
    with pytest.raises(WorkflowRegistrationConflict):
        repository.update_metadata(FLOW_ID, 7, {"name": "bypass"})
    with registration_store.transaction() as session:
        assert session.get(Flow, FLOW_ID).name == "flow"
