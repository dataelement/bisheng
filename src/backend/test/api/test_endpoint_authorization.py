"""Authentication/authorization regressions for four reported endpoints.

GHSA-p2wv-9g25-xrqr:
- report_temp: missing login (CWE-306)
- dataset/del, mark/del, file_bbox: missing per-resource authorization (CWE-862/639)
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.exceptions.auth import AuthJWTException
from bisheng.main import handle_http_exception


def build_app(router):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.add_exception_handler(BaseErrorCode, handle_http_exception)
    # Mirrors main.py: a missing/invalid token is a 401 before the handler runs.
    app.add_exception_handler(
        AuthJWTException,
        lambda request, exc: JSONResponse(status_code=401, content={"detail": str(exc)}),
    )
    return app


def login_as(app, user):
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user


def normal_user():
    return UserPayload(user_id=2, user_name="normal", tenant_id=1, user_role=[], is_global_super=False)


def admin_user():
    # AdminRole == 1 (bisheng.database.constants)
    return UserPayload(user_id=9, user_name="admin", tenant_id=1, user_role=[1], is_global_super=False)


async def call(app, method, path, **kwargs):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


# --- report_temp -----------------------------------------------------------


@pytest.fixture
def report_env(monkeypatch):
    from bisheng.api.v1 import report as report_module

    report = SimpleNamespace(
        flow_id="flow-1",
        object_name="reports/secret.docx",
        version_key="v1",
        newversion_key="n1",
        del_yn=0,
    )

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def exec(self, *_args, **_kwargs):
            return SimpleNamespace(first=lambda: report)

        def add(self, *_args):
            return None

        def commit(self):
            return None

        def refresh(self, *_args):
            return None

    monkeypatch.setattr(report_module, "get_sync_db_session", lambda: FakeSession())
    minio = SimpleNamespace(get_share_link=AsyncMock(return_value="https://minio/presigned-secret"))
    monkeypatch.setattr(report_module, "get_minio_storage", AsyncMock(return_value=minio))
    monkeypatch.setattr(report_module, "check_business_action", AsyncMock(return_value=True), raising=False)
    return SimpleNamespace(module=report_module, app=build_app(report_module.router), minio=minio)


async def test_report_temp_rejects_unauthenticated(report_env):
    response = await call(report_env.app, "GET", "/api/v1/report/report_temp", params={"flow_id": "flow-1"})
    assert response.status_code == 401
    report_env.minio.get_share_link.assert_not_awaited()


async def test_report_temp_rejects_foreign_flow(report_env):
    login_as(report_env.app, normal_user())
    report_env.module.check_business_action.return_value = False
    response = await call(report_env.app, "GET", "/api/v1/report/report_temp", params={"flow_id": "flow-1"})
    assert response.json()["status_code"] == 403
    report_env.minio.get_share_link.assert_not_awaited()


async def test_report_temp_allows_visible_flow(report_env):
    login_as(report_env.app, normal_user())
    response = await call(report_env.app, "GET", "/api/v1/report/report_temp", params={"flow_id": "flow-1"})
    assert response.json()["status_code"] == 200
    report_env.module.check_business_action.assert_awaited_once()


# --- dataset/del -----------------------------------------------------------


@pytest.fixture
def dataset_env(monkeypatch):
    from bisheng.api.services import dataset_service as service_module
    from bisheng.api.v1 import dataset as dataset_module

    dataset = SimpleNamespace(id=7, user_id=1, object_name="dataset/secret.csv")
    monkeypatch.setattr(service_module.DatasetDao, "filter_dataset_by_ids", lambda _ids: [dataset])
    delete = Mock()
    monkeypatch.setattr(service_module.DatasetDao, "delete", delete)
    monkeypatch.setattr(
        service_module, "get_minio_storage_sync", lambda: SimpleNamespace(remove_object_sync=lambda **_k: None)
    )
    return SimpleNamespace(app=build_app(dataset_module.router), delete=delete)


async def test_dataset_delete_rejects_other_users_dataset(dataset_env):
    login_as(dataset_env.app, normal_user())
    response = await call(dataset_env.app, "DELETE", "/api/v1/dataset/del", params={"dataset_id": 7})
    assert response.json()["status_code"] == 403
    dataset_env.delete.assert_not_called()


async def test_dataset_delete_allows_owner(dataset_env):
    login_as(dataset_env.app, UserPayload(user_id=1, user_name="owner", tenant_id=1, user_role=[]))
    response = await call(dataset_env.app, "DELETE", "/api/v1/dataset/del", params={"dataset_id": 7})
    assert response.json()["status_code"] == 200
    dataset_env.delete.assert_called_once()


async def test_dataset_delete_allows_admin(dataset_env):
    login_as(dataset_env.app, admin_user())
    response = await call(dataset_env.app, "DELETE", "/api/v1/dataset/del", params={"dataset_id": 7})
    assert response.json()["status_code"] == 200
    dataset_env.delete.assert_called_once()


# --- mark/del --------------------------------------------------------------


@pytest.fixture
def mark_env(monkeypatch):
    from bisheng.api.v1 import mark_task as mark_module

    task = SimpleNamespace(id=11, create_id=1, process_users="5", tenant_id=1)
    monkeypatch.setattr(mark_module.MarkTaskDao, "get_task_byid", staticmethod(lambda _id: task))
    delete_task = Mock()
    monkeypatch.setattr(mark_module.MarkTaskDao, "delete_task", delete_task)
    del_record = Mock()
    monkeypatch.setattr(mark_module.MarkRecordDao, "del_record", del_record)
    return SimpleNamespace(app=build_app(mark_module.router), task=task, delete_task=delete_task, del_record=del_record)


async def test_mark_delete_rejects_unrelated_user(mark_env):
    login_as(mark_env.app, normal_user())
    response = await call(mark_env.app, "DELETE", "/api/v1/mark/del", params={"task_id": 11})
    assert response.json()["status_code"] == 403
    mark_env.delete_task.assert_not_called()
    mark_env.del_record.assert_not_called()


async def test_mark_delete_allows_creator(mark_env):
    login_as(mark_env.app, UserPayload(user_id=1, user_name="creator", tenant_id=1, user_role=[]))
    response = await call(mark_env.app, "DELETE", "/api/v1/mark/del", params={"task_id": 11})
    assert response.json()["status_code"] == 200
    mark_env.delete_task.assert_called_once()
    mark_env.del_record.assert_called_once()


async def test_mark_delete_allows_assignee(mark_env):
    login_as(mark_env.app, UserPayload(user_id=5, user_name="assignee", tenant_id=1, user_role=[]))
    response = await call(mark_env.app, "DELETE", "/api/v1/mark/del", params={"task_id": 11})
    assert response.json()["status_code"] == 200
    mark_env.delete_task.assert_called_once()


async def test_mark_delete_allows_admin(mark_env):
    login_as(mark_env.app, admin_user())
    response = await call(mark_env.app, "DELETE", "/api/v1/mark/del", params={"task_id": 11})
    assert response.json()["status_code"] == 200
    mark_env.delete_task.assert_called_once()


# --- knowledge/file_bbox ---------------------------------------------------


@pytest.fixture
def bbox_env(monkeypatch):
    from bisheng.knowledge.api.endpoints import knowledge as knowledge_module

    monkeypatch.setattr(
        knowledge_module,
        "require_business_action",
        AsyncMock(side_effect=UnAuthorizedError()),
        raising=False,
    )
    monkeypatch.setattr(
        knowledge_module.KnowledgeFileDao,
        "query_by_id",
        AsyncMock(return_value=SimpleNamespace(id=3, bbox_object_name="bbox/secret.json")),
    )
    read_bbox = Mock(return_value={"blocks": ["secret"]})
    monkeypatch.setattr(knowledge_module.KnowledgeService, "get_file_bbox", read_bbox)
    return SimpleNamespace(module=knowledge_module, app=build_app(knowledge_module.router), read_bbox=read_bbox)


async def test_file_bbox_rejects_unauthorized_file(bbox_env):
    login_as(bbox_env.app, normal_user())
    response = await call(bbox_env.app, "GET", "/api/v1/knowledge/file_bbox", params={"file_id": 3})
    assert response.json()["status_code"] == 403
    bbox_env.read_bbox.assert_not_called()


async def test_file_bbox_allows_authorized_file(bbox_env):
    login_as(bbox_env.app, normal_user())
    bbox_env.module.require_business_action.side_effect = None
    bbox_env.module.require_business_action.return_value = None
    response = await call(bbox_env.app, "GET", "/api/v1/knowledge/file_bbox", params={"file_id": 3})
    assert response.json()["status_code"] == 200
    bbox_env.read_bbox.assert_called_once()
