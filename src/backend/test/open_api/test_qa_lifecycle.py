"""Behaviour of the v2 QA endpoints: query, delete, update and add."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from bisheng.open_api.api import dependencies as open_api_dependencies
from bisheng.open_api.api.exception_handlers import open_api_http_status, register_open_api_exception_handlers
from bisheng.open_endpoints.api.endpoints import filelib
from bisheng.open_endpoints.domain.schemas.filelib import APIAddQAParam, APIAppendQAParam, QueryQAParam

USER = SimpleNamespace(user_id=7)


# --- query_qa -------------------------------------------------------------


def test_query_qa_returns_every_source(monkeypatch):
    query = Mock(return_value=[])
    monkeypatch.setattr(filelib, "get_open_api_operator", Mock(return_value=USER))
    monkeypatch.setattr(filelib.QAKnoweldgeDao, "query_by_condition_v1", query)

    filelib.query_qa(QueryQAParam(timeRange=["2026-01-01", "2026-12-31"]))

    query.assert_called_once_with(create_start="2026-01-01", create_end="2026-12-31")


def test_query_by_condition_v1_has_no_source_filter_by_default(monkeypatch):
    from contextlib import contextmanager

    from bisheng.knowledge.domain.models import knowledge_file

    captured = []

    class Session:
        def exec(self, sql):
            captured.append(sql)
            return SimpleNamespace(all=lambda: [])

    @contextmanager
    def session():
        yield Session()

    monkeypatch.setattr(knowledge_file, "get_sync_db_session", session)

    knowledge_file.QAKnoweldgeDao.query_by_condition_v1(create_start="2026-01-01", create_end="2026-12-31")
    knowledge_file.QAKnoweldgeDao.query_by_condition_v1(create_start="2026-01-01", create_end="2026-12-31", source=[1])

    assert "source" not in str(captured[0].whereclause)
    assert "source" in str(captured[1].whereclause)


@pytest.mark.parametrize("time_range", [[], ["2026-01-01"]])
def test_query_qa_rejects_short_time_range(time_range):
    with pytest.raises(ValidationError):
        QueryQAParam(timeRange=time_range)


async def test_query_qa_short_time_range_is_http_400(monkeypatch):
    @asynccontextmanager
    async def authenticated(request, inspect_body=False):
        yield

    # The validation handler re-runs authentication first; treat the caller as authenticated.
    monkeypatch.setattr(open_api_dependencies, "open_api_access_context", authenticated)
    app = FastAPI()
    register_open_api_exception_handlers(app)

    @app.post("/api/v2/filelib/query_qa")
    def endpoint(param: QueryQAParam):
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v2/filelib/query_qa", json={"timeRange": ["2026-01-01"]})

    assert response.status_code == 400
    assert response.json()["status_code"] == 400


# --- delete_qa_data -------------------------------------------------------


@pytest.fixture
def qa_writes(monkeypatch):
    knowledge = SimpleNamespace(id=23, type=1)
    writes = SimpleNamespace(
        knowledge=knowledge,
        update=Mock(),
        delete_batch=Mock(),
        delete_vector=Mock(),
        save=Mock(),
        telemetry=Mock(),
    )
    monkeypatch.setattr(filelib, "get_open_api_operator", Mock(return_value=USER))
    monkeypatch.setattr(filelib.QAKnoweldgeDao, "update", writes.update)
    monkeypatch.setattr(filelib.QAKnoweldgeDao, "delete_batch", writes.delete_batch)
    monkeypatch.setattr(filelib.knowledge_imp, "delete_vector_data", writes.delete_vector)
    monkeypatch.setattr(filelib.knowledge_imp, "QA_save_knowledge", writes.save)
    monkeypatch.setattr(filelib.telemetry_service, "log_event_sync", writes.telemetry)
    return writes


def _grant(monkeypatch, writes, qa):
    monkeypatch.setattr(filelib, "_qa_with_knowledge_access", Mock(return_value=(qa, writes.knowledge)))


def test_delete_last_question_deletes_whole_pair(monkeypatch, qa_writes):
    qa = SimpleNamespace(id=11, knowledge_id=23, questions=["only"], answers='["a"]')
    _grant(monkeypatch, qa_writes, qa)

    response = filelib.delete_qa_data(qa_id=11, question="only")

    assert response.status_code == 200
    qa_writes.delete_batch.assert_called_once_with([11])
    qa_writes.delete_vector.assert_called_once_with(qa_writes.knowledge, file_ids=[11])
    qa_writes.update.assert_not_called()
    qa_writes.save.assert_not_called()


def test_delete_one_of_several_questions_keeps_pair(monkeypatch, qa_writes):
    qa = SimpleNamespace(id=11, knowledge_id=23, questions=["q1", "q2"], answers='["a"]')
    _grant(monkeypatch, qa_writes, qa)

    filelib.delete_qa_data(qa_id=11, question="q1")

    assert qa.questions == ["q2"]
    qa_writes.update.assert_called_once_with(qa)
    qa_writes.delete_batch.assert_not_called()
    qa_writes.delete_vector.assert_called_once_with(qa_writes.knowledge, file_ids=[11])
    qa_writes.save.assert_called_once_with(qa_writes.knowledge, qa)


# --- update_qa ------------------------------------------------------------


def test_update_answer_only_rebuilds_index(monkeypatch, qa_writes):
    qa = SimpleNamespace(id=11, knowledge_id=23, questions=["q1", "q2"], answers='["old"]')
    _grant(monkeypatch, qa_writes, qa)

    filelib.update_qa(id=11, question=None, original_question=None, answer=["new"])

    assert qa.questions == ["q1", "q2"]
    assert qa.answers == '["new"]'
    qa_writes.update.assert_called_once_with(qa)
    qa_writes.delete_vector.assert_called_once_with(qa_writes.knowledge, file_ids=[11])
    qa_writes.save.assert_called_once_with(qa_writes.knowledge, qa)


def test_update_question_only_replaces_question_list(monkeypatch, qa_writes):
    qa = SimpleNamespace(id=11, knowledge_id=23, questions=["q1", "q2"], answers='["a"]')
    _grant(monkeypatch, qa_writes, qa)

    filelib.update_qa(id=11, question="new", original_question=None, answer=None)

    assert qa.questions == ["new"]
    assert qa.answers == '["a"]'
    qa_writes.save.assert_called_once_with(qa_writes.knowledge, qa)


def test_update_without_changes_does_not_touch_index(monkeypatch, qa_writes):
    qa = SimpleNamespace(id=11, knowledge_id=23, questions=["q1"], answers='["a"]')
    _grant(monkeypatch, qa_writes, qa)

    filelib.update_qa(id=11, question=None, original_question=None, answer=None)

    qa_writes.delete_vector.assert_not_called()
    qa_writes.save.assert_not_called()


# --- add_qa / add_relative_qa ---------------------------------------------


def _assert_type_not_supported(raised):
    assert raised.value.status_code == 10962
    assert open_api_http_status(raised.value) == 400


def test_add_qa_rejects_document_knowledge(monkeypatch):
    add = Mock()
    monkeypatch.setattr(filelib, "get_open_api_operator", Mock(return_value=USER))
    monkeypatch.setattr(
        filelib.KnowledgeService, "judge_knowledge_access", Mock(return_value=SimpleNamespace(id=23, type=0))
    )
    monkeypatch.setattr(filelib.knowledge_imp, "add_qa", add)

    with pytest.raises(HTTPException) as raised:
        filelib.add_qa(knowledge_id=23, data=[APIAddQAParam(question="q", answer=["a"])])

    _assert_type_not_supported(raised)
    add.assert_not_called()


def test_add_relative_qa_rejects_document_knowledge(monkeypatch):
    add = Mock()
    qa = SimpleNamespace(id=11, knowledge_id=23)
    monkeypatch.setattr(filelib, "get_open_api_operator", Mock(return_value=USER))
    monkeypatch.setattr(filelib, "_qa_with_knowledge_access", Mock(return_value=(qa, SimpleNamespace(id=23, type=0))))
    monkeypatch.setattr(filelib.knowledge_imp, "add_qa", add)

    with pytest.raises(HTTPException) as raised:
        filelib.append_qa(knowledge_id=23, data=APIAppendQAParam(id="11", relative_questions=["q2"]))

    _assert_type_not_supported(raised)
    add.assert_not_called()
