"""Managed app list enrichment must leave versions for the explicit version read."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bisheng.api.services import workflow


@pytest.mark.parametrize("managed", [True, False])
def test_build_list_skips_versions_without_changing_other_list_consumers(monkeypatch, managed):
    version_query = Mock(return_value=[SimpleNamespace(flow_id="flow", id=1, name="v1")])
    monkeypatch.setattr(workflow.FlowVersionDao, "get_list_by_flow_ids", version_query)
    monkeypatch.setattr(workflow.UserDao, "get_user_by_ids", lambda _: [])
    monkeypatch.setattr(workflow.TagDao, "get_tags_by_resource", lambda *_: {})
    monkeypatch.setattr(workflow.WorkFlowService, "get_logo_share_link", lambda _: None)
    rows = workflow.WorkFlowService.add_extra_field(
        object(), [{"id": "flow", "flow_type": 10, "user_id": 7, "logo": None}], managed=managed
    )
    if managed:
        version_query.assert_not_called()
        assert rows[0]["version_list"] == []
    else:
        version_query.assert_called_once_with(["flow"])
        assert rows[0]["version_list"][0]["name"] == "v1"
