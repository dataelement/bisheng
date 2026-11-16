"""Public response regression: only proven SQL credentials are removed."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.schemas.api import resp_200
from bisheng.workflow.application.kunlian_workflow_api import KunlianWorkflowApi


def sensitive_record():
    return {
        "id": "flow",
        "name": "safe",
        "tenant_id": 7,
        "user_id": 99,
        "data": {
            "nodes": [
                {
                    "data": {
                        "group_params": [
                            {
                                "params": [
                                    {"key": "sql_agent", "value": {"db_password": "private", "db_name": "reports"}}
                                ]
                            }
                        ]
                    }
                }
            ]
        },
    }


@pytest.mark.parametrize("method", ["detail", "create_version"])
async def test_graph_response_redacts_credentials_and_internal_fields(method):
    original = sensitive_record()
    owner = AsyncMock(return_value=resp_200(original))
    service = KunlianWorkflowApi(
        target_reader=AsyncMock(return_value={"tenant_id": 7, "flow_type": 10}),
        flow_service=SimpleNamespace(get_management_flow=owner, create_new_version=owner),
    )
    user = SimpleNamespace(user_id=17, tenant_id=7)
    if method == "detail":
        response = await service.detail(user, "flow", for_edit=True)
    else:
        response = await service.create_version(user, "flow", SimpleNamespace(flow_type=10))
    assert "private" not in str(response.data)
    assert "tenant_id" not in response.data
    assert "user_id" not in response.data
    assert original["data"]["nodes"][0]["data"]["group_params"][0]["params"][0]["value"]["db_password"] == "private"


async def test_summary_detail_never_includes_graph():
    service = KunlianWorkflowApi(
        target_reader=AsyncMock(return_value={"tenant_id": 7, "flow_type": 10}),
        flow_service=SimpleNamespace(get_management_flow=AsyncMock(return_value=resp_200(sensitive_record()))),
    )
    response = await service.detail(SimpleNamespace(user_id=17, tenant_id=7), "flow")
    assert "data" not in response.data


def test_shared_response_helper_preserves_revision_and_owner_errors():
    from bisheng.common.errcode.flow import VersionNameExistsError
    from bisheng.workflow.domain.schemas.kunlian_redaction import redact_workflow_response

    record = sensitive_record() | {"draft_revision": "cas-revision"}
    result = redact_workflow_response(record)
    assert result["draft_revision"] == "cas-revision"
    assert "private" not in str(result)
    failure = VersionNameExistsError.return_resp()
    assert redact_workflow_response(failure) is failure


def test_metadata_repository_never_returns_graph(monkeypatch):
    from bisheng.workflow.domain.repositories.kunlian_workflow_api import KunlianWorkflowMetadataRepository

    record = sensitive_record() | {"flow_type": 10, "status": 1}
    flow = SimpleNamespace(**record, model_dump=lambda: record)
    repository = KunlianWorkflowMetadataRepository()
    session = SimpleNamespace(add=lambda value: None, flush=lambda: None)

    @contextmanager
    def transaction():
        yield session

    monkeypatch.setattr(repository, "transaction", transaction)
    monkeypatch.setattr(repository, "_flow", lambda *args, **kwargs: flow)
    result = repository.update_metadata("flow", 7, {"description": "new"})
    assert "data" not in result
    assert "tenant_id" not in result
    assert "user_id" not in result
