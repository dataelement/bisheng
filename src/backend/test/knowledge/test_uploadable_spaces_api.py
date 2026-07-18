"""F028 T014 — integration test for GET /api/v1/knowledge/space/uploadable.

Mounts the real knowledge_space router on a minimal app, overrides the
KnowledgeSpaceService dependency with a stub that returns a curated list,
and verifies the endpoint's response envelope.

AC coverage: AC-17
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import FastAPI
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import ORJSONResponse
from starlette import status
from starlette.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.api.endpoints.knowledge_space import router as ks_router
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum


# --- Lightweight handlers (mirror production main.py) ---------------------


def _handle_http_exception(req, exc):
    if isinstance(exc, HTTPException):
        msg = {'status_code': exc.status_code, 'status_message': exc.detail}
    elif isinstance(exc, BaseErrorCode):
        data = {'exception': str(exc), **exc.kwargs} if exc.kwargs else {'exception': str(exc)}
        msg = {'status_code': exc.code, 'status_message': exc.message, 'data': data}
    else:
        msg = {'status_code': 500, 'status_message': str(exc)}
    return ORJSONResponse(content=msg)


def _handle_validation_error(req, exc):
    return ORJSONResponse(
        content={'status_code': status.HTTP_422_UNPROCESSABLE_ENTITY, 'status_message': exc.errors()},
    )


_EXCEPTION_HANDLERS = {
    HTTPException: _handle_http_exception,
    RequestValidationError: _handle_validation_error,
    BaseErrorCode: _handle_http_exception,
}


# --- Stubs ----------------------------------------------------------------


class _FakeUser:
    user_id = 1
    user_name = 'Admin'
    tenant_id = 1

    def is_admin(self):
        return False


def _make_knowledge(id_: int, name: str, description: Optional[str] = None) -> Knowledge:
    return Knowledge(
        id=id_, name=name, description=description, user_id=1,
        type=KnowledgeTypeEnum.SPACE.value,
        update_time=datetime(2026, 5, 31), tenant_id=1,
    )


class _FakeKnowledgeSpaceService:
    """Returns a curated space list; captures the keyword for assertions."""

    def __init__(self, spaces: list[Knowledge]):
        self._spaces = spaces
        self.last_keyword = '__unset__'  # sentinel: distinguish None vs missing

    async def list_uploadable_spaces(self, *, keyword=None, limit=200):
        self.last_keyword = keyword
        if keyword:
            kw = keyword.lower()
            return [s for s in self._spaces if s.name and kw in s.name.lower()]
        return list(self._spaces)


def _make_app(svc: _FakeKnowledgeSpaceService) -> FastAPI:
    app = FastAPI(exception_handlers=_EXCEPTION_HANDLERS)
    app.include_router(ks_router, prefix='/api/v1')

    async def _get_user():
        return _FakeUser()

    async def _get_svc():
        return svc

    app.dependency_overrides[UserPayload.get_login_user] = _get_user
    app.dependency_overrides[get_knowledge_space_service] = _get_svc
    return app


# --- Tests ----------------------------------------------------------------


def test_uploadable_returns_list_without_keyword():
    """AC-17: GET /uploadable → 200, body.data is a list of {id, name, icon, description}."""
    svc = _FakeKnowledgeSpaceService([
        _make_knowledge(42, '宏观研究', description='宏观'),
        _make_knowledge(56, '黄金专题'),
    ])
    app = _make_app(svc)
    with TestClient(app) as client:
        resp = client.get('/api/v1/knowledge/space/uploadable')

    assert resp.status_code == 200
    body = resp.json()
    assert body['status_code'] == 200
    rows = body['data']['data']
    assert [r['id'] for r in rows] == [42, 56]
    # Each row has the canonical shape.
    for r in rows:
        assert set(r.keys()) == {'id', 'name', 'icon', 'description'}
        assert r['icon'] is None  # Knowledge has no icon field — always None
    assert svc.last_keyword is None


def test_uploadable_keyword_passed_through():
    """AC-17: GET /uploadable?keyword=黄金 — service receives the keyword."""
    svc = _FakeKnowledgeSpaceService([
        _make_knowledge(42, '宏观研究'),
        _make_knowledge(56, '黄金专题'),
    ])
    app = _make_app(svc)
    with TestClient(app) as client:
        resp = client.get('/api/v1/knowledge/space/uploadable?keyword=黄金')

    assert resp.status_code == 200
    rows = resp.json()['data']['data']
    assert [r['id'] for r in rows] == [56]
    assert svc.last_keyword == '黄金'


def test_uploadable_empty_returns_empty_list():
    """AC-17: 用户无可上传空间 → data.data = []。"""
    svc = _FakeKnowledgeSpaceService([])
    app = _make_app(svc)
    with TestClient(app) as client:
        resp = client.get('/api/v1/knowledge/space/uploadable')

    body = resp.json()
    assert body['status_code'] == 200
    assert body['data']['data'] == []
