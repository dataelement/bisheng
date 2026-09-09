from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from bisheng.common.errcode.permission import (
    PermissionInvalidResourceError,
    PermissionServiceUnavailableError,
)
from bisheng.open_api.domain.scopes import get_open_api_scope_marker
from bisheng.open_endpoints.api.endpoints import filelib
from bisheng.open_endpoints.domain.schemas.filelib import QueryQAParam
from bisheng.permission.application import business_authorization
from bisheng.permission.domain.services.permission_action_service import PermissionActor


def test_qa_lookup_authorizes_owning_library_before_return(monkeypatch):
    user = SimpleNamespace(user_id=7)
    qa = SimpleNamespace(id=11, knowledge_id=23)
    knowledge = SimpleNamespace(id=23)
    judge = Mock(return_value=knowledge)
    monkeypatch.setattr(filelib.QAKnoweldgeDao, "get_qa_knowledge_by_primary_id", Mock(return_value=qa))
    monkeypatch.setattr(filelib.KnowledgeService, "judge_knowledge_access", judge)

    resolved_qa, resolved_knowledge = filelib._qa_with_knowledge_access(
        11,
        login_user=user,
        action="visible",
    )

    assert resolved_qa is qa
    assert resolved_knowledge is knowledge
    judge.assert_called_once_with(user, 23, "visible")


def test_update_qa_denial_has_no_dao_or_index_side_effect(monkeypatch):
    denied = HTTPException(status_code=403, detail="denied")
    monkeypatch.setattr(filelib, "get_open_api_operator", Mock(return_value=SimpleNamespace(user_id=7)))
    monkeypatch.setattr(filelib, "_qa_with_knowledge_access", Mock(side_effect=denied))
    update = Mock()
    save = Mock()
    delete_vector = Mock()
    monkeypatch.setattr(filelib.QAKnoweldgeDao, "update", update)
    monkeypatch.setattr(filelib.knowledge_imp, "QA_save_knowledge", save)
    monkeypatch.setattr(filelib.knowledge_imp, "delete_vector_data", delete_vector)

    with pytest.raises(HTTPException) as raised:
        filelib.update_qa(id=11, question="changed", answer=["answer"])

    assert raised.value.status_code == 403
    update.assert_not_called()
    save.assert_not_called()
    delete_vector.assert_not_called()


def test_detail_qa_uses_visible_permission(monkeypatch):
    user = SimpleNamespace(user_id=7)
    qa = SimpleNamespace(id=11, knowledge_id=23)
    authorize = Mock(return_value=(qa, SimpleNamespace(id=23)))
    monkeypatch.setattr(filelib, "get_open_api_operator", Mock(return_value=user))
    monkeypatch.setattr(filelib, "_qa_with_knowledge_access", authorize)

    response = filelib.detail_qa(id=11)

    assert response.data is qa
    authorize.assert_called_once_with(11, login_user=user, action="visible")


def test_query_qa_keeps_open_api_authentication_marker():
    marker = get_open_api_scope_marker(filelib.query_qa)

    assert marker is not None
    assert marker.scope == "knowledge:read"
    assert marker.modes == frozenset({"S", "D"})


def test_query_qa_deduplicates_libraries_and_preserves_visible_rows(monkeypatch):
    user = SimpleNamespace(user_id=7)
    qa_rows = [
        SimpleNamespace(id=11, knowledge_id=23, answers='["a1"]'),
        SimpleNamespace(id=12, knowledge_id=23, answers='["a2"]'),
        SimpleNamespace(id=13, knowledge_id=24, answers='["a3"]'),
        SimpleNamespace(id=14, knowledge_id=23, answers='["a4"]'),
    ]
    action_map = Mock(return_value={23: {"visible"}, 24: set()})
    monkeypatch.setattr(filelib, "get_open_api_operator", Mock(return_value=user))
    monkeypatch.setattr(filelib.QAKnoweldgeDao, "query_by_condition_v1", Mock(return_value=qa_rows))
    monkeypatch.setattr(
        filelib.KnowledgeService.permission_service,
        "get_knowledge_action_map_sync",
        action_map,
    )

    response = filelib.query_qa(QueryQAParam(timeRange=["2026-01-01", "2026-12-31"]))

    assert [qa.id for qa in response.data] == [11, 12, 14]
    assert [qa.answers for qa in response.data] == [["a1"], ["a2"], ["a4"]]
    action_map.assert_called_once_with(user, [23, 24], ["visible"])


def test_query_qa_filters_invalid_resources_and_malformed_answers(monkeypatch):
    user = SimpleNamespace(user_id=7)
    qa_rows = [
        SimpleNamespace(id=11, knowledge_id=None, answers='["orphan"]'),
        SimpleNamespace(id=12, knowledge_id="bad", answers='["bad id"]'),
        SimpleNamespace(id=13, knowledge_id=-1, answers='["negative id"]'),
        SimpleNamespace(id=14, knowledge_id="23", answers='["valid"]'),
        SimpleNamespace(id=15, knowledge_id=23, answers="not-json"),
        SimpleNamespace(id=16, knowledge_id=24, answers='["deleted library"]'),
    ]
    action_map = Mock(return_value={23: {"visible"}, 24: set()})
    monkeypatch.setattr(filelib, "get_open_api_operator", Mock(return_value=user))
    monkeypatch.setattr(filelib.QAKnoweldgeDao, "query_by_condition_v1", Mock(return_value=qa_rows))
    monkeypatch.setattr(
        filelib.KnowledgeService.permission_service,
        "get_knowledge_action_map_sync",
        action_map,
    )

    response = filelib.query_qa(QueryQAParam(timeRange=["2026-01-01", "2026-12-31"]))

    assert [qa.id for qa in response.data] == [14]
    assert response.data[0].answers == ["valid"]
    action_map.assert_called_once_with(user, [23, 24], ["visible"])


def test_query_qa_skips_permission_lookup_without_valid_candidates(monkeypatch):
    user = SimpleNamespace(user_id=7)
    action_map = Mock()
    monkeypatch.setattr(filelib, "get_open_api_operator", Mock(return_value=user))
    monkeypatch.setattr(
        filelib.QAKnoweldgeDao,
        "query_by_condition_v1",
        Mock(return_value=[SimpleNamespace(id=11, knowledge_id=None, answers='["orphan"]')]),
    )
    monkeypatch.setattr(
        filelib.KnowledgeService.permission_service,
        "get_knowledge_action_map_sync",
        action_map,
    )

    response = filelib.query_qa(QueryQAParam(timeRange=["2026-01-01", "2026-12-31"]))

    assert response.data == []
    action_map.assert_not_called()


def test_query_qa_fails_closed_when_permission_service_is_unavailable(monkeypatch):
    user = SimpleNamespace(user_id=7)
    qa = SimpleNamespace(id=11, knowledge_id=23, answers='["answer"]')
    action_map = Mock(side_effect=PermissionServiceUnavailableError())
    monkeypatch.setattr(filelib, "get_open_api_operator", Mock(return_value=user))
    monkeypatch.setattr(filelib.QAKnoweldgeDao, "query_by_condition_v1", Mock(return_value=[qa]))
    monkeypatch.setattr(
        filelib.KnowledgeService.permission_service,
        "get_knowledge_action_map_sync",
        action_map,
    )

    with pytest.raises(PermissionServiceUnavailableError):
        filelib.query_qa(QueryQAParam(timeRange=["2026-01-01", "2026-12-31"]))

    assert qa.answers == '["answer"]'


async def test_batch_permission_isolates_invalid_legacy_resource(monkeypatch):
    actor = PermissionActor(user_id=7, current_tenant_id=1)

    class Registry:
        async def resolve(self, *, resource_type, resource_id, actor, action):
            del resource_type, actor, action
            if resource_id == "24":
                raise PermissionInvalidResourceError()
            return SimpleNamespace(resource_id=resource_id)

    class Runtime:
        async def batch_check_actions(self, actor, targets, action):
            del actor, action
            return tuple(target.resource_id == "23" for target in targets)

    async def resolve_actor(login_user):
        del login_user
        return actor

    async def get_registry():
        return Registry()

    async def get_runtime():
        return Runtime()

    monkeypatch.setattr(business_authorization, "resolve_permission_actor", resolve_actor)
    monkeypatch.setattr(business_authorization, "get_f048_resource_registry", get_registry)
    monkeypatch.setattr(business_authorization, "get_f048_runtime", get_runtime)

    action_map = await business_authorization.batch_check_business_actions(
        object(),
        resource_type="knowledge_library",
        resource_ids=[23, 24],
        actions=["visible"],
    )

    assert action_map == {"23": frozenset({"visible"}), "24": frozenset()}
