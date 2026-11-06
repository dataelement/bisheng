"""GET status/info cannot create a model-change operation or enqueue legacy jobs.

覆盖 AC: AC-68, AC-71, AC-79, AC-91, AC-92.
Actual query service/endpoint and existing visibility/diagnostic fixtures run;
SQL and queue transports are isolated. Explicit model writes own dispatch.
"""

from unittest.mock import Mock

import pytest

from bisheng.common.errcode.knowledge import KnowledgeRebuildingError
from bisheng.knowledge.api.endpoints import knowledge as endpoint
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState
from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_knowledge_celery
from test.knowledge import test_knowledge_space_info_optimization as fixtures

info_case = fixtures.info_case


@pytest.mark.parametrize("state", [KnowledgeState.REBUILDING.value, KnowledgeState.FAILED.value])
async def test_visible_space_info_reports_pending_state_without_dispatching(info_case, state):
    info_case.space.state = state
    before = info_case.space.model_dump()
    result = await info_case.service.get_space_info(info_case.space.id)
    assert result.state == state and result.actions == ["visible"]
    assert info_case.space.model_dump() == before
    info_case.rebuild.assert_not_called()
    assert [call.kwargs["action"] for call in info_case.check.await_args_list] == ["visible"]
    metric = info_case.metric.call_args.kwargs
    assert metric["status"] == "success" and metric["rebuild_elapsed_ms"] >= 0


@pytest.mark.parametrize("state", [KnowledgeState.REBUILDING.value, KnowledgeState.FAILED.value])
def test_status_keeps_existing_pending_error_without_starting_rebuild(monkeypatch, state):
    knowledge = Knowledge(id=9, tenant_id=1, user_id=7, name="personal", type=2, model="11", state=state)
    query = Mock(return_value=[knowledge])
    monkeypatch.setattr(endpoint.KnowledgeDao, "get_user_knowledge", query)
    dispatch = Mock()
    monkeypatch.setattr(rebuild_knowledge_celery, "delay", dispatch)
    user = Mock(user_id=7)
    with pytest.raises(KnowledgeRebuildingError):
        endpoint.get_knowledge_status(login_user=user)
    assert knowledge.state == state and knowledge.model == "11" and knowledge.model_transition is None
    dispatch.assert_not_called()
    query.assert_called_once_with(7, None, endpoint.KnowledgeTypeEnum.PRIVATE)
