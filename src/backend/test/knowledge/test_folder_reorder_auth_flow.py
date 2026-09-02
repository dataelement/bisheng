"""F106 文件夹排序鉴权流转: 171 MySQL, HTTP + SELECT knowledgefile.sort_weight."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.services.permission_service import PermissionService
from test.knowledge.test_space_reorder_auth_flow import (
    WEIGHT_BAND,
    _admin_user,
    _cleanup,
    _in_ids,
    _insert_space,
    _ops_user,
    _plain_user,
    reorder_flow_env,
)


@pytest.fixture
async def flow_env(monkeypatch):
    async with reorder_flow_env(monkeypatch) as env:
        yield env


def _folder_app(user) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        return JSONResponse(
            {"status_code": exc.code, "status_message": exc.message, "data": None},
            status_code=200,
        )

    @app.post("/api/v1/knowledge/space/{space_id}/folders/{folder_id}/sort")
    async def sort_folder(space_id: int, folder_id: int, payload: dict):
        svc = KnowledgeSpaceService(request=None, login_user=user)
        await svc.reorder_folder(
            space_id,
            folder_id,
            prev_folder_id=payload.get("prev_folder_id"),
            next_folder_id=payload.get("next_folder_id"),
        )
        return resp_200(data=True)

    return app


async def _insert_folder(
    session: AsyncSession,
    *,
    space_id: int,
    name: str,
    file_level_path: str,
    sort_weight: int | None,
) -> int:
    await session.execute(
        text(
            """
            INSERT INTO knowledgefile
              (user_id, knowledge_id, file_name, file_type, file_level_path, sort_weight, tenant_id)
            VALUES (1, :kid, :name, 0, :path, :w, 1)
            """
        ),
        {"kid": space_id, "name": name, "path": file_level_path, "w": sort_weight},
    )
    await session.flush()
    return int(
        (
            await session.execute(
                text("SELECT id FROM knowledgefile WHERE knowledge_id = :kid AND file_name = :n"),
                {"kid": space_id, "n": name},
            )
        ).scalar_one()
    )


async def _folder_weights(session: AsyncSession, ids: list[int]) -> dict[int, int | None]:
    rows = (
        await session.execute(
            _in_ids("SELECT id, sort_weight FROM knowledgefile WHERE id IN :ids"),
            {"ids": list(ids)},
        )
    ).all()
    return {int(row[0]): (int(row[1]) if row[1] is not None else None) for row in rows}


async def _post_folder_sort(app, space_id: int, folder_id: int, prev_id: int | None, next_id: int | None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            f"/api/v1/knowledge/space/{space_id}/folders/{folder_id}/sort",
            json={"prev_folder_id": prev_id, "next_folder_id": next_id},
        )


@pytest.mark.asyncio
async def test_admin_and_manager_folder_reorder_operator_member_denied(flow_env, monkeypatch):
    """AT-04/08/13/14/16/17/18: 管理员与库管可拖当前目录; 运营岗/成员/仅子文件夹管理员拒绝."""
    engine, fixture_ids = flow_env
    suffix = uuid.uuid4().hex[:8]
    space_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            space_id = await _insert_space(
                session,
                name=f"f106-folder-space-{suffix}",
                level=KnowledgeSpaceLevelEnum.PUBLIC,
                sort_weight=WEIGHT_BAND + 50_000,
            )
            root_a = await _insert_folder(
                session,
                space_id=space_id,
                name=f"f106-root-a-{suffix}",
                file_level_path="",
                sort_weight=WEIGHT_BAND + 2000,
            )
            root_b = await _insert_folder(
                session,
                space_id=space_id,
                name=f"f106-root-b-{suffix}",
                file_level_path="",
                sort_weight=WEIGHT_BAND,
            )
            parent = await _insert_folder(
                session,
                space_id=space_id,
                name=f"f106-parent-{suffix}",
                file_level_path="",
                sort_weight=WEIGHT_BAND + 4000,
            )
            await session.commit()
            child_a = await _insert_folder(
                session,
                space_id=space_id,
                name=f"f106-child-a-{suffix}",
                file_level_path=f"/{parent}",
                sort_weight=WEIGHT_BAND + 2000,
            )
            child_b = await _insert_folder(
                session,
                space_id=space_id,
                name=f"f106-child-b-{suffix}",
                file_level_path=f"/{parent}",
                sort_weight=WEIGHT_BAND,
            )
            await session.commit()
        space_ids = [space_id]
        fixture_ids.add(space_id)

        admin_app = _folder_app(_admin_user())
        moved = await _post_folder_sort(admin_app, space_id, root_a, None, root_b)
        assert moved.json()["status_code"] == 200
        async with AsyncSession(engine, expire_on_commit=False) as session:
            weights = await _folder_weights(session, [root_a, root_b])
        assert weights[root_a] == WEIGHT_BAND - 1000
        assert weights[root_b] == WEIGHT_BAND

        async def _check_manager(**kwargs):
            object_type = kwargs.get("object_type")
            object_id = str(kwargs.get("object_id"))
            if object_type == "knowledge_space" and object_id == str(space_id):
                return True
            if object_type == "folder" and object_id == str(parent):
                return True
            return False

        monkeypatch.setattr(PermissionService, "check", AsyncMock(side_effect=_check_manager))
        manager = SimpleNamespace(
            user_id=88010620,
            user_name="f106-space-admin",
            tenant_id=1,
            is_admin=lambda: False,
            is_global_super=False,
            role_names=["普通用户"],
        )
        manager_app = _folder_app(manager)
        root_ok = await _post_folder_sort(manager_app, space_id, root_a, root_b, None)
        assert root_ok.json()["status_code"] == 200
        nested_ok = await _post_folder_sort(manager_app, space_id, child_a, None, child_b)
        assert nested_ok.json()["status_code"] == 200

        async def _check_child_only(**kwargs):
            return kwargs.get("object_type") == "folder" and str(kwargs.get("object_id")) == str(child_a)

        monkeypatch.setattr(PermissionService, "check", AsyncMock(side_effect=_check_child_only))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            before = await _folder_weights(session, [root_a, root_b])
        child_admin_denied = await _post_folder_sort(manager_app, space_id, root_a, None, root_b)
        assert child_admin_denied.json()["status_code"] == SpacePermissionDeniedError.Code

        monkeypatch.setattr(PermissionService, "check", AsyncMock(return_value=False))
        ops_denied = await _post_folder_sort(_folder_app(_ops_user()), space_id, root_a, None, root_b)
        assert ops_denied.json()["status_code"] == SpacePermissionDeniedError.Code
        member_denied = await _post_folder_sort(_folder_app(_plain_user()), space_id, root_a, None, root_b)
        assert member_denied.json()["status_code"] == SpacePermissionDeniedError.Code
        dept_denied = await _post_folder_sort(
            _folder_app(
                SimpleNamespace(
                    user_id=88010603,
                    user_name="f106-dept-admin",
                    tenant_id=1,
                    is_admin=lambda: False,
                    is_global_super=False,
                    role_names=["部门管理员"],
                )
            ),
            space_id,
            root_a,
            None,
            root_b,
        )
        assert dept_denied.json()["status_code"] == SpacePermissionDeniedError.Code
        async with AsyncSession(engine, expire_on_commit=False) as session:
            after = await _folder_weights(session, [root_a, root_b])
        assert after == before
        again = await _post_folder_sort(_folder_app(_ops_user()), space_id, root_a, None, root_b)
        assert again.json()["status_code"] == SpacePermissionDeniedError.Code
    finally:
        await _cleanup(engine, space_ids)
