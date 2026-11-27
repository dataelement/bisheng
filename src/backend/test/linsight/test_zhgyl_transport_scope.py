"""Current transport scope and one-fetch history bridge; no remote services."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.tools import BaseTool
from pydantic import ValidationError

from bisheng.linsight.domain.services import transport_tools as transport


class UnusedExecutor(BaseTool):
    name: str = "synthetic_executor"
    description: str = "Must be replaced by the deterministic boundary mock"

    def _run(self, **kwargs):
        raise AssertionError("Unexpected executor")


def test_transport_schema_has_current_waybill_and_physical_fields():
    conditions = transport.Conditions.model_fields
    target = transport.Target.model_fields
    assert {"master_numbers", "house_numbers", "gross_weight_kg"} <= set(conditions)
    assert not {"net_weight_kg", "package_count"} & set(conditions)
    assert {"gross_weight", "gross_weight_kg", "packaging"} <= set(target)
    assert not {"net_weight", "net_weight_kg", "package_count"} & set(target)
    pair = transport.ToolInput.model_validate(
        {"request": {"action": "history", "query": {"master_numbers": ["MBL"], "house_numbers": ["HBL"]}}}
    )
    assert pair.request.query.master_numbers == ["MBL"]


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "show", "sort": "invoice_date_desc"},
        {"action": "history", "query": {"date_field": "invoice_date"}},
        {"action": "history", "query": {"package_count": 1}},
        {"action": "history", "query": {"net_weight_kg": 100}},
    ],
)
def test_retired_transport_public_parameters_are_not_offered(payload):
    with pytest.raises(ValidationError):
        transport.ToolInput.model_validate({"request": payload})


async def test_history_never_fetches_a_recommendation_pool():
    request = {"action": "history", "query": {"master_numbers": ["MBL"], "house_numbers": ["HBL"]}}
    envelope = {
        "protocol": transport.PROTOCOL,
        "status": "final",
        "outcome": "ok",
        "terminal": True,
        "next_action": "none",
        "answer": "Synthetic history",
    }
    tool = transport.TransportTool(inner=UnusedExecutor(), workspace=object())
    with (
        patch.object(transport, "fetch_and_upload", AsyncMock(return_value=[])) as fetch,
        patch.object(transport.TransportTool, "_fixed", AsyncMock(return_value=envelope)) as fixed,
    ):
        content, artifact = await tool._arun(request)
    fetch.assert_awaited_once_with(request, tool.workspace)
    fixed.assert_awaited_once_with({**request, "receipts": []}, None)
    assert json.loads(content)["outcome"] == "ok"
    assert artifact["terminal"] is True
