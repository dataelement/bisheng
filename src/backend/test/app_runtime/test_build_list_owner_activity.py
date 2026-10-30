"""The build projection distinguishes original owners from permission-model grants."""

from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("delete,expected", [(0, True), (1, False), (None, False)])
def test_owner_status_reuses_the_existing_batch_lookup(monkeypatch, delete, expected):
    from bisheng.api.services import workflow

    service = workflow.WorkFlowService
    monkeypatch.setattr(service, "enabled_app_types", lambda: {35})
    owners = [] if delete is None else [SimpleNamespace(user_id=7, user_name="Owner", delete=delete)]
    monkeypatch.setattr(workflow.UserDao, "get_user_by_ids", lambda _: owners)
    monkeypatch.setattr(workflow.FlowVersionDao, "get_list_by_flow_ids", lambda _: [])
    monkeypatch.setattr(workflow.TagDao, "get_tags_by_resource", lambda *args: {})
    monkeypatch.setattr(service, "get_logo_share_link", lambda _: None)
    rows = service.add_extra_field(
        SimpleNamespace(user_id=8), [{"id": "app", "user_id": 7, "flow_type": 35, "logo": None}]
    )
    assert rows[0]["owner_active"] is expected
