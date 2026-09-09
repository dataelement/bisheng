from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from bisheng.open_endpoints.api.endpoints import filelib


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
