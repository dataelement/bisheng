import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from bisheng.open_mcp import qa as qa_service
from bisheng.open_mcp.contracts import (
    QaAddInput,
    QaAddRelativeInput,
    QaDeleteInput,
    QaDetailInput,
    QaQueryInput,
    QaUpdateInput,
)
from bisheng.open_mcp.tools import qa as qa_tools


def _qa_row(**overrides):
    row = {
        "id": 7,
        "knowledge_id": 11,
        "questions": ["报销期限是多久"],
        "answers": json.dumps(["30 天内"], ensure_ascii=False),
        "user_id": 3,
        "source": 3,
        "status": 1,
        "extra_meta": "{}",
        "remark": "",
        "tenant_id": 1,
    }
    row.update(overrides)
    return SimpleNamespace(**row, dict=lambda: dict(row))


@pytest.fixture
def operator(monkeypatch):
    user = SimpleNamespace(user_id=3)
    monkeypatch.setattr(qa_service, "get_open_api_operator", lambda: user)
    return user


def test_inputs_reject_unknown_fields_and_bad_ranges():
    with pytest.raises(ValidationError):
        QaQueryInput(time_range=["2026-01-01 00:00:00"])
    with pytest.raises(ValidationError):
        QaDetailInput(id=0)
    with pytest.raises(ValidationError):
        QaAddInput(knowledge_id=1, data=[{"question": "q", "answer": ["a"], "tenant_id": 2}])
    with pytest.raises(ValidationError):
        QaAddInput(knowledge_id=1, data=[])
    with pytest.raises(ValidationError):
        QaUpdateInput(id=1, original_question="old")


@pytest.mark.asyncio
async def test_detail_handler_decodes_answers_and_hides_unlisted_fields(monkeypatch):
    async def fake_detail(*, qa_id):
        assert qa_id == 7
        return _qa_row(secret_internal="x")

    monkeypatch.setattr(qa_service, "detail_qa", fake_detail)

    result = await qa_tools.qa_detail(QaDetailInput(id=7))

    assert result.answers == ["30 天内"]
    assert result.questions == ["报销期限是多久"]
    assert "secret_internal" not in result.model_dump()
    assert "tenant_id" not in result.model_dump()


@pytest.mark.asyncio
async def test_malformed_legacy_answers_map_to_empty_list(monkeypatch):
    async def fake_detail(*, qa_id):
        return _qa_row(answers="not-json")

    monkeypatch.setattr(qa_service, "detail_qa", fake_detail)

    result = await qa_tools.qa_detail(QaDetailInput(id=7))

    assert result.answers == []


@pytest.mark.asyncio
async def test_query_handler_returns_items_and_total(monkeypatch):
    async def fake_query(*, time_range):
        assert time_range == ["2026-01-01 00:00:00", "2026-12-31 23:59:59"]
        return [_qa_row(), _qa_row(id=8)]

    monkeypatch.setattr(qa_service, "query_qa", fake_query)

    result = await qa_tools.qa_query(QaQueryInput(time_range=["2026-01-01 00:00:00", "2026-12-31 23:59:59"]))

    assert result.total == 2
    assert [item.id for item in result.items] == [7, 8]


@pytest.mark.asyncio
async def test_query_filters_invisible_and_malformed_rows(monkeypatch, operator):
    visible = _qa_row(id=1, knowledge_id=11)
    hidden = _qa_row(id=2, knowledge_id=12)
    bad_resource = _qa_row(id=3, knowledge_id="oops")
    bad_answers = _qa_row(id=4, knowledge_id=11, answers="not-json")
    monkeypatch.setattr(
        qa_service.QAKnoweldgeDao,
        "query_by_condition_v1",
        lambda **kwargs: [visible, hidden, bad_resource, bad_answers],
    )
    permission = MagicMock()
    permission.get_knowledge_action_map_sync.return_value = {11: {"visible"}, 12: set()}
    monkeypatch.setattr(qa_service.KnowledgeService, "permission_service", permission)

    rows = await qa_service.query_qa(time_range=["a", "b"])

    assert [row.id for row in rows] == [1]
    assert rows[0].answers == ["30 天内"]


@pytest.mark.asyncio
async def test_detail_requires_visible_permission_on_owning_library(monkeypatch, operator):
    row = _qa_row()
    monkeypatch.setattr(qa_service.QAKnoweldgeDao, "get_qa_knowledge_by_primary_id", lambda qa_id: row)
    judge = MagicMock(return_value=object())
    monkeypatch.setattr(qa_service.KnowledgeService, "judge_knowledge_access", judge)

    assert await qa_service.detail_qa(qa_id=7) is row

    judge.assert_called_once_with(operator, 11, "visible")


@pytest.mark.asyncio
async def test_detail_of_missing_entry_is_not_found(monkeypatch, operator):
    monkeypatch.setattr(qa_service.QAKnoweldgeDao, "get_qa_knowledge_by_primary_id", lambda qa_id: None)

    with pytest.raises(HTTPException) as exc:
        await qa_service.detail_qa(qa_id=7)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_checks_edit_access_and_marks_source_api(monkeypatch, operator):
    knowledge = object()
    judge = MagicMock(return_value=knowledge)
    monkeypatch.setattr(qa_service.KnowledgeService, "judge_knowledge_access", judge)
    saved = []

    def fake_add_qa(db_knowledge, upsert):
        assert db_knowledge is knowledge
        saved.append(upsert)
        return _qa_row(id=100 + len(saved))

    monkeypatch.setattr(qa_service.knowledge_imp, "add_qa", fake_add_qa)

    result = await qa_tools.qa_add(
        QaAddInput(
            knowledge_id=11,
            data=[
                {"question": "q1", "answer": ["a1"], "extra": {"k": "v"}},
                {"question": "q2", "answer": ["a2"]},
            ],
        )
    )

    judge.assert_called_once_with(operator, 11, "edit")
    assert result.total == 2
    assert [item.source for item in saved] == [3, 3]
    assert saved[0].questions == ["q1"]
    assert json.loads(saved[0].extra_meta) == {"k": "v"}
    assert json.loads(saved[1].extra_meta) == {}
    assert saved[0].user_id == 3


@pytest.mark.asyncio
async def test_add_relative_rejects_entry_from_another_library(monkeypatch, operator):
    monkeypatch.setattr(qa_service.QAKnoweldgeDao, "get_qa_knowledge_by_primary_id", lambda qa_id: _qa_row())
    monkeypatch.setattr(qa_service.KnowledgeService, "judge_knowledge_access", MagicMock(return_value=object()))
    add = MagicMock()
    monkeypatch.setattr(qa_service.knowledge_imp, "add_qa", add)

    with pytest.raises(HTTPException) as exc:
        await qa_tools.qa_add_relative(QaAddRelativeInput(knowledge_id=99, id=7, relative_questions=["x"]))

    assert exc.value.status_code == 404
    add.assert_not_called()


@pytest.mark.asyncio
async def test_update_replaces_only_the_named_similar_question(monkeypatch, operator):
    row = _qa_row(questions=["a", "b", "c"])
    row.answers = json.dumps(["old"])
    monkeypatch.setattr(qa_service.QAKnoweldgeDao, "get_qa_knowledge_by_primary_id", lambda qa_id: row)
    knowledge = object()
    monkeypatch.setattr(qa_service.KnowledgeService, "judge_knowledge_access", MagicMock(return_value=knowledge))
    updated = []
    monkeypatch.setattr(qa_service.QAKnoweldgeDao, "update", lambda item: updated.append(item))
    deleted, saved = MagicMock(), MagicMock()
    monkeypatch.setattr(qa_service.knowledge_imp, "delete_vector_data", deleted)
    monkeypatch.setattr(qa_service.knowledge_imp, "QA_save_knowledge", saved)

    result = await qa_tools.qa_update(QaUpdateInput(id=7, original_question="b", question="B", answer=["new"]))

    assert result.success is True
    assert row.questions == ["a", "B", "c"]
    assert json.loads(row.answers) == ["new"]
    assert updated == [row]
    deleted.assert_called_once_with(knowledge, file_ids=[7])
    saved.assert_called_once_with(knowledge, row)


@pytest.mark.asyncio
async def test_delete_without_question_removes_entry_and_vectors(monkeypatch, operator):
    row = _qa_row()
    monkeypatch.setattr(qa_service.QAKnoweldgeDao, "get_qa_knowledge_by_primary_id", lambda qa_id: row)
    knowledge = object()
    judge = MagicMock(return_value=knowledge)
    monkeypatch.setattr(qa_service.KnowledgeService, "judge_knowledge_access", judge)
    delete_batch, deleted, saved = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(qa_service.QAKnoweldgeDao, "delete_batch", delete_batch)
    monkeypatch.setattr(qa_service.knowledge_imp, "delete_vector_data", deleted)
    monkeypatch.setattr(qa_service.knowledge_imp, "QA_save_knowledge", saved)

    result = await qa_tools.qa_delete(QaDeleteInput(id=7))

    assert result.success is True
    judge.assert_called_once_with(operator, 11, "edit")
    delete_batch.assert_called_once_with([7])
    deleted.assert_called_once_with(knowledge, file_ids=[7])
    saved.assert_not_called()


@pytest.mark.asyncio
async def test_delete_one_similar_question_keeps_entry_and_reindexes(monkeypatch, operator):
    row = _qa_row(questions=["a", "b"])
    monkeypatch.setattr(qa_service.QAKnoweldgeDao, "get_qa_knowledge_by_primary_id", lambda qa_id: row)
    knowledge = object()
    monkeypatch.setattr(qa_service.KnowledgeService, "judge_knowledge_access", MagicMock(return_value=knowledge))
    delete_batch, saved = MagicMock(), MagicMock()
    updated = []
    monkeypatch.setattr(qa_service.QAKnoweldgeDao, "delete_batch", delete_batch)
    monkeypatch.setattr(qa_service.QAKnoweldgeDao, "update", lambda item: updated.append(item))
    monkeypatch.setattr(qa_service.knowledge_imp, "delete_vector_data", MagicMock())
    monkeypatch.setattr(qa_service.knowledge_imp, "QA_save_knowledge", saved)

    await qa_tools.qa_delete(QaDeleteInput(id=7, question="a"))

    assert row.questions == ["b"]
    delete_batch.assert_not_called()
    assert updated == [row]
    saved.assert_called_once_with(knowledge, row)
