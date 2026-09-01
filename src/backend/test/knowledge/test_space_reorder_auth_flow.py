"""F106 库排序鉴权流转: 171 MySQL, HTTP + SELECT sort_weight + 再打一枪."""

from __future__ import annotations

import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge_space import (
    SpaceInvalidLevelError,
    SpacePermissionDeniedError,
)
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScopeDao,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.user.domain.services.platform_operator import PLATFORM_OPERATOR_ROLE_NAME

WEIGHT_BAND = 800_000_000
SPACE_TYPE = KnowledgeTypeEnum.SPACE.value


def _mysql_async_url() -> str:
    override = os.environ.get("QA_EXPERT_FLOW_DATABASE_URL") or os.environ.get("ORG_LEVEL_FLOW_DATABASE_URL")
    if override:
        return override.replace("pymysql", "aiomysql")
    from bisheng.core.config.settings import decrypt_token

    cfg_name = os.environ.get("config", "config.yaml")
    cfg_path = Path(__file__).resolve().parents[2] / "bisheng" / Path(cfg_name).name
    loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    url = loaded["database_url"]
    if not isinstance(url, str):
        raise RuntimeError("config.yaml database_url 不是字符串")
    match = re.search(r"(?<=:)[^:]+(?=@)", url)
    if match:
        url = re.sub(r"(?<=:)[^:]+(?=@)", decrypt_token(match.group(0)), url)
    if "171" not in url and not override:
        raise RuntimeError("流转测试默认打 192.168.106.171, 请确认 config.yaml")
    return url.replace("pymysql", "aiomysql")


def _admin_user():
    return SimpleNamespace(
        user_id=1,
        user_name="f106-admin",
        tenant_id=1,
        is_admin=lambda: True,
        is_global_super=True,
        role="admin",
        role_names=["系统管理员"],
    )


def _ops_user(*, user_id: int = 88010601):
    return SimpleNamespace(
        user_id=user_id,
        user_name="f106-ops",
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
        role="user",
        role_names=[PLATFORM_OPERATOR_ROLE_NAME],
    )


def _plain_user(*, user_id: int = 88010602):
    return SimpleNamespace(
        user_id=user_id,
        user_name="f106-member",
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
        role="user",
        role_names=["普通用户"],
    )


def _dept_admin_user(*, user_id: int = 88010603):
    return SimpleNamespace(
        user_id=user_id,
        user_name="f106-dept-admin",
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
        role="user",
        role_names=["部门管理员"],
    )


def _sort_app(user) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        return JSONResponse(
            {"status_code": exc.code, "status_message": exc.message, "data": None},
            status_code=200,
        )

    @app.post("/api/v1/knowledge/space/{space_id}/sort")
    async def sort_space(space_id: int, payload: dict):
        svc = KnowledgeSpaceService(request=None, login_user=user)
        await svc.reorder_space(
            space_id,
            prev_space_id=payload.get("prev_space_id"),
            next_space_id=payload.get("next_space_id"),
        )
        return resp_200(data=True)

    @app.get("/api/v1/knowledge/space/level/{space_level}")
    async def list_level(space_level: str):
        svc = KnowledgeSpaceService(request=None, login_user=user)
        if space_level == KnowledgeSpaceLevelEnum.PUBLIC.value:
            spaces = await svc.get_public_spaces("sort_weight")
        else:
            spaces = await svc.get_spaces_by_level(space_level, "sort_weight")
        return resp_200(spaces)

    return app


async def _insert_space(
    session: AsyncSession,
    *,
    name: str,
    level: KnowledgeSpaceLevelEnum,
    sort_weight: int | None,
    owner_type: KnowledgeSpaceOwnerTypeEnum = KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
    owner_id: int = 1,
    user_id: int = 1,
) -> int:
    await session.execute(
        text(
            """
            INSERT INTO knowledge
              (user_id, name, type, tenant_id, sort_weight, is_released, is_favorite, auth_type)
            VALUES (:uid, :name, :type, 1, :w, 0, 0, 'PRIVATE')
            """
        ),
        {"uid": user_id, "name": name, "type": SPACE_TYPE, "w": sort_weight},
    )
    await session.flush()
    space_id = int((await session.execute(text("SELECT id FROM knowledge WHERE name = :n"), {"n": name})).scalar_one())
    await session.execute(
        text(
            """
            INSERT INTO knowledge_space_scope
              (tenant_id, space_id, level, owner_type, owner_id, created_by)
            VALUES (1, :sid, :level, :ot, :oid, :uid)
            """
        ),
        {
            "sid": space_id,
            "level": level.value,
            "ot": owner_type.value,
            "oid": owner_id,
            "uid": user_id,
        },
    )
    return space_id


def _in_ids(sql: str):
    return text(sql).bindparams(bindparam("ids", expanding=True))


async def _weights(session: AsyncSession, ids: list[int]) -> dict[int, int | None]:
    rows = (
        await session.execute(_in_ids("SELECT id, sort_weight FROM knowledge WHERE id IN :ids"), {"ids": list(ids)})
    ).all()
    return {int(row[0]): (int(row[1]) if row[1] is not None else None) for row in rows}


@asynccontextmanager
async def reorder_flow_env(monkeypatch):
    """171 MySQL 会话补丁 + 把 level 工作集裁到本用例插入的 ID, 避免重铺打到现网行."""
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.core.database.connection import _patch_aiomysql_pre_ping

    set_current_tenant_id(1)
    _patch_aiomysql_pre_ping()
    engine = create_async_engine(_mysql_async_url(), pool_pre_ping=True)
    fixture_ids: set[int] = set()

    @asynccontextmanager
    async def patched_session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    session_targets = (
        "bisheng.core.database.get_async_db_session",
        "bisheng.knowledge.domain.models.knowledge.get_async_db_session",
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        "bisheng.knowledge.domain.models.knowledge_space_file.get_async_db_session",
        "bisheng.knowledge.domain.models.knowledge_space_scope.get_async_db_session",
        "bisheng.knowledge.domain.models.department_knowledge_space.get_async_db_session",
        "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        "bisheng.knowledge.domain.services.knowledge_space_pin_service.get_async_db_session",
        "bisheng.common.models.space_channel_member.get_async_db_session",
        "bisheng.database.models.department.get_async_db_session",
    )
    for target in session_targets:
        monkeypatch.setattr(target, patched_session)

    orig_by_levels = KnowledgeSpaceScopeDao.aget_space_ids_by_levels
    orig_by_level = KnowledgeSpaceScopeDao.aget_space_ids_by_level

    async def _filtered_levels(levels):
        ids = await orig_by_levels(levels)
        if not fixture_ids:
            return ids
        return [space_id for space_id in ids if int(space_id) in fixture_ids]

    async def _filtered_level(level):
        ids = await orig_by_level(level)
        if not fixture_ids:
            return ids
        return [space_id for space_id in ids if int(space_id) in fixture_ids]

    monkeypatch.setattr(KnowledgeSpaceScopeDao, "aget_space_ids_by_levels", _filtered_levels)
    monkeypatch.setattr(KnowledgeSpaceScopeDao, "aget_space_ids_by_level", _filtered_level)

    try:
        yield engine, fixture_ids
    finally:
        await engine.dispose()


@pytest.fixture
async def flow_env(monkeypatch):
    async with reorder_flow_env(monkeypatch) as env:
        yield env


async def _post_sort(app, space_id: int, prev_id: int | None, next_id: int | None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            f"/api/v1/knowledge/space/{space_id}/sort",
            json={"prev_space_id": prev_id, "next_space_id": next_id},
        )


async def _cleanup(engine, space_ids: list[int], dept_ids: list[int] | None = None) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        if space_ids:
            await session.execute(
                _in_ids("DELETE FROM department_knowledge_space WHERE space_id IN :ids"),
                {"ids": list(space_ids)},
            )
            await session.execute(
                _in_ids("DELETE FROM knowledge_space_scope WHERE space_id IN :ids"),
                {"ids": list(space_ids)},
            )
            await session.execute(
                _in_ids("DELETE FROM knowledgefile WHERE knowledge_id IN :ids"),
                {"ids": list(space_ids)},
            )
            await session.execute(
                _in_ids("DELETE FROM knowledge WHERE id IN :ids"),
                {"ids": list(space_ids)},
            )
        if dept_ids:
            await session.execute(
                _in_ids("DELETE FROM department WHERE id IN :ids"),
                {"ids": list(dept_ids)},
            )
        await session.commit()


@pytest.mark.asyncio
async def test_admin_reorder_public_and_department_and_team_ks_flow(flow_env):
    """AT-01/02/03/21/24: 系统管理员拖公共/部门库, 团队旁科室, 跨组邻居 18041, 连续写."""
    engine, fixture_ids = flow_env
    suffix = uuid.uuid4().hex[:8]
    space_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            pub_a = await _insert_space(
                session,
                name=f"f106-pub-a-{suffix}",
                level=KnowledgeSpaceLevelEnum.PUBLIC,
                sort_weight=WEIGHT_BAND + 2000,
                owner_type=KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
            )
            pub_b = await _insert_space(
                session,
                name=f"f106-pub-b-{suffix}",
                level=KnowledgeSpaceLevelEnum.PUBLIC,
                sort_weight=WEIGHT_BAND,
                owner_type=KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
            )
            dept_a = await _insert_space(
                session,
                name=f"f106-dept-a-{suffix}",
                level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                sort_weight=WEIGHT_BAND + 2000,
            )
            dept_b = await _insert_space(
                session,
                name=f"f106-dept-b-{suffix}",
                level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                sort_weight=WEIGHT_BAND,
            )
            team = await _insert_space(
                session,
                name=f"f106-team-{suffix}",
                level=KnowledgeSpaceLevelEnum.TEAM,
                sort_weight=WEIGHT_BAND + 10_000,
                owner_type=KnowledgeSpaceOwnerTypeEnum.USER_GROUP,
            )
            clinic = await _insert_space(
                session,
                name=f"f106-ks-{suffix}",
                level=KnowledgeSpaceLevelEnum.TEAM_KS,
                sort_weight=WEIGHT_BAND + 12_000,
                owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
            )
            await session.commit()
        space_ids = [pub_a, pub_b, dept_a, dept_b, team, clinic]
        fixture_ids.update(space_ids)

        app = _sort_app(_admin_user())
        moved = await _post_sort(app, pub_a, None, pub_b)
        assert moved.status_code == 200
        assert moved.json()["status_code"] == 200
        assert moved.json()["data"] is True
        async with AsyncSession(engine, expire_on_commit=False) as session:
            weights = await _weights(session, [pub_a, pub_b])
        assert weights[pub_a] == WEIGHT_BAND - 1000
        assert weights[pub_b] == WEIGHT_BAND

        again = await _post_sort(app, pub_a, pub_b, None)
        assert again.json()["status_code"] == 200
        async with AsyncSession(engine, expire_on_commit=False) as session:
            weights = await _weights(session, [pub_a, pub_b])
        assert weights[pub_a] == WEIGHT_BAND + 1000
        assert weights[pub_b] == WEIGHT_BAND

        dept_moved = await _post_sort(app, dept_a, None, dept_b)
        assert dept_moved.json()["status_code"] == 200
        async with AsyncSession(engine, expire_on_commit=False) as session:
            weights = await _weights(session, [dept_a, dept_b])
        assert weights[dept_a] == WEIGHT_BAND - 1000
        assert weights[dept_b] == WEIGHT_BAND

        team_moved = await _post_sort(app, team, clinic, None)
        assert team_moved.json()["status_code"] == 200
        async with AsyncSession(engine, expire_on_commit=False) as session:
            weights = await _weights(session, [team, clinic])
        assert weights[team] == WEIGHT_BAND + 13_000
        assert weights[clinic] == WEIGHT_BAND + 12_000

        before = None
        async with AsyncSession(engine, expire_on_commit=False) as session:
            before = await _weights(session, [pub_a, dept_a])
        denied = await _post_sort(app, pub_a, None, dept_a)
        assert denied.json()["status_code"] == SpaceInvalidLevelError.Code
        async with AsyncSession(engine, expire_on_commit=False) as session:
            after = await _weights(session, [pub_a, dept_a])
        assert after == before
        denied_again = await _post_sort(app, pub_a, None, dept_a)
        assert denied_again.json()["status_code"] == SpaceInvalidLevelError.Code
    finally:
        await _cleanup(engine, space_ids)


@pytest.mark.asyncio
async def test_operator_public_department_ok_team_denied_and_not_admin(flow_env):
    """AT-05/06/07/40: 运营岗 is_admin=false, 可拖公共/部门库, 团队 18040 无脏写."""
    engine, fixture_ids = flow_env
    suffix = uuid.uuid4().hex[:8]
    ops = _ops_user()
    assert ops.is_admin() is False
    space_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            pub_a = await _insert_space(
                session,
                name=f"f106-ops-pub-a-{suffix}",
                level=KnowledgeSpaceLevelEnum.PUBLIC,
                sort_weight=WEIGHT_BAND + 2000,
                owner_type=KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
            )
            pub_b = await _insert_space(
                session,
                name=f"f106-ops-pub-b-{suffix}",
                level=KnowledgeSpaceLevelEnum.PUBLIC,
                sort_weight=WEIGHT_BAND,
                owner_type=KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
            )
            dept_a = await _insert_space(
                session,
                name=f"f106-ops-dept-a-{suffix}",
                level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                sort_weight=WEIGHT_BAND + 2000,
            )
            dept_b = await _insert_space(
                session,
                name=f"f106-ops-dept-b-{suffix}",
                level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                sort_weight=WEIGHT_BAND,
            )
            team = await _insert_space(
                session,
                name=f"f106-ops-team-{suffix}",
                level=KnowledgeSpaceLevelEnum.TEAM,
                sort_weight=WEIGHT_BAND + 20_000,
                owner_type=KnowledgeSpaceOwnerTypeEnum.USER_GROUP,
            )
            clinic = await _insert_space(
                session,
                name=f"f106-ops-ks-{suffix}",
                level=KnowledgeSpaceLevelEnum.TEAM_KS,
                sort_weight=WEIGHT_BAND + 21_000,
            )
            await session.commit()
        space_ids = [pub_a, pub_b, dept_a, dept_b, team, clinic]
        fixture_ids.update(space_ids)
        app = _sort_app(ops)

        pub_moved = await _post_sort(app, pub_a, None, pub_b)
        assert pub_moved.json()["status_code"] == 200
        async with AsyncSession(engine, expire_on_commit=False) as session:
            weights = await _weights(session, [pub_a, pub_b])
        assert weights[pub_a] == WEIGHT_BAND - 1000

        dept_moved = await _post_sort(app, dept_a, None, dept_b)
        assert dept_moved.json()["status_code"] == 200
        async with AsyncSession(engine, expire_on_commit=False) as session:
            weights = await _weights(session, [dept_a])
        assert weights[dept_a] == WEIGHT_BAND - 1000

        async with AsyncSession(engine, expire_on_commit=False) as session:
            before = await _weights(session, [team, clinic])
        denied = await _post_sort(app, team, None, clinic)
        assert denied.json()["status_code"] == SpacePermissionDeniedError.Code
        async with AsyncSession(engine, expire_on_commit=False) as session:
            after = await _weights(session, [team, clinic])
        assert after == before
        denied_again = await _post_sort(app, team, None, clinic)
        assert denied_again.json()["status_code"] == SpacePermissionDeniedError.Code
        clinic_denied = await _post_sort(app, clinic, team, None)
        assert clinic_denied.json()["status_code"] == SpacePermissionDeniedError.Code
    finally:
        await _cleanup(engine, space_ids)


@pytest.mark.asyncio
async def test_member_and_space_admin_cannot_reorder_space_personal_invalid(flow_env):
    """AT-15/18/19: 库管与成员拖库 18040; 个人库 18041."""
    engine, fixture_ids = flow_env
    suffix = uuid.uuid4().hex[:8]
    owner_id = 88010610
    space_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            owned = await _insert_space(
                session,
                name=f"f106-owned-{suffix}",
                level=KnowledgeSpaceLevelEnum.PUBLIC,
                sort_weight=WEIGHT_BAND + 30_000,
                owner_type=KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
                user_id=owner_id,
            )
            neighbour = await _insert_space(
                session,
                name=f"f106-owned-n-{suffix}",
                level=KnowledgeSpaceLevelEnum.PUBLIC,
                sort_weight=WEIGHT_BAND + 31_000,
                owner_type=KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
            )
            personal = await _insert_space(
                session,
                name=f"f106-personal-{suffix}",
                level=KnowledgeSpaceLevelEnum.PERSONAL,
                sort_weight=WEIGHT_BAND + 32_000,
                owner_type=KnowledgeSpaceOwnerTypeEnum.USER,
                owner_id=owner_id,
                user_id=owner_id,
            )
            await session.commit()
        space_ids = [owned, neighbour, personal]
        fixture_ids.update(space_ids)

        owner = SimpleNamespace(
            user_id=owner_id,
            user_name="f106-owner",
            tenant_id=1,
            is_admin=lambda: False,
            is_global_super=False,
            role="user",
            role_names=["普通用户"],
        )
        async with AsyncSession(engine, expire_on_commit=False) as session:
            before = await _weights(session, [owned, personal])
        owner_denied = await _post_sort(_sort_app(owner), owned, None, neighbour)
        assert owner_denied.json()["status_code"] == SpacePermissionDeniedError.Code
        member_denied = await _post_sort(_sort_app(_plain_user()), owned, None, neighbour)
        assert member_denied.json()["status_code"] == SpacePermissionDeniedError.Code
        personal_denied = await _post_sort(_sort_app(_admin_user()), personal, None, None)
        assert personal_denied.json()["status_code"] == SpaceInvalidLevelError.Code
        async with AsyncSession(engine, expire_on_commit=False) as session:
            after = await _weights(session, [owned, personal])
        assert after == before
        owner_again = await _post_sort(_sort_app(owner), owned, None, neighbour)
        assert owner_again.json()["status_code"] == SpacePermissionDeniedError.Code
    finally:
        await _cleanup(engine, space_ids)


@pytest.mark.asyncio
async def test_department_admin_bound_team_ok_unbound_and_public_denied_respread(flow_env, monkeypatch):
    """AT-09~12/22/23: 部门管理员按绑定表拖团队/科室, 未绑定与公共库拒绝, 重铺不写出工作集."""
    engine, fixture_ids = flow_env
    suffix = uuid.uuid4().hex[:8]
    space_ids: list[int] = []
    dept_ids: list[int] = []
    admin_dept_ids: set[int] = set()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                text(
                    """
                    INSERT INTO department
                      (dept_id, name, parent_id, tenant_id, path, status, source, org_level, is_deleted)
                    VALUES
                      (:d, :n, NULL, 1, :p, 'active', 'local', 'dept', 0)
                    """
                ),
                {"d": f"f106-dept-{suffix}", "n": f"f106部门-{suffix}", "p": f"/tmp-{suffix}/"},
            )
            await session.commit()
            dept_id = int(
                (
                    await session.execute(
                        text("SELECT id FROM department WHERE dept_id = :d"),
                        {"d": f"f106-dept-{suffix}"},
                    )
                ).scalar_one()
            )
            await session.execute(
                text("UPDATE department SET path = :p WHERE id = :id"),
                {"p": f"/{dept_id}/", "id": dept_id},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO department
                      (dept_id, name, parent_id, tenant_id, path, status, source, org_level, is_deleted)
                    VALUES
                      (:d, :n, :pid, 1, :p, 'active', 'local', 'office', 0)
                    """
                ),
                {
                    "d": f"f106-other-{suffix}",
                    "n": f"f106其他-{suffix}",
                    "pid": dept_id,
                    "p": f"/{dept_id}/tmp-o/",
                },
            )
            await session.commit()
            other_id = int(
                (
                    await session.execute(
                        text("SELECT id FROM department WHERE dept_id = :d"),
                        {"d": f"f106-other-{suffix}"},
                    )
                ).scalar_one()
            )
            await session.execute(
                text("UPDATE department SET path = :p WHERE id = :id"),
                {"p": f"/{other_id}/", "id": other_id},
            )
            bound_team = await _insert_space(
                session,
                name=f"f106-bind-team-{suffix}",
                level=KnowledgeSpaceLevelEnum.TEAM,
                sort_weight=None,
                owner_type=KnowledgeSpaceOwnerTypeEnum.USER_GROUP,
            )
            bound_ks = await _insert_space(
                session,
                name=f"f106-bind-ks-{suffix}",
                level=KnowledgeSpaceLevelEnum.TEAM_KS,
                sort_weight=None,
                owner_id=dept_id,
            )
            unbound = await _insert_space(
                session,
                name=f"f106-unbound-{suffix}",
                level=KnowledgeSpaceLevelEnum.TEAM,
                sort_weight=WEIGHT_BAND + 40_000,
                owner_type=KnowledgeSpaceOwnerTypeEnum.USER_GROUP,
            )
            outsider = await _insert_space(
                session,
                name=f"f106-out-{suffix}",
                level=KnowledgeSpaceLevelEnum.TEAM,
                sort_weight=None,
                owner_type=KnowledgeSpaceOwnerTypeEnum.USER_GROUP,
            )
            other_bound = await _insert_space(
                session,
                name=f"f106-other-bound-{suffix}",
                level=KnowledgeSpaceLevelEnum.TEAM,
                sort_weight=WEIGHT_BAND + 41_000,
                owner_type=KnowledgeSpaceOwnerTypeEnum.USER_GROUP,
            )
            public_a = await _insert_space(
                session,
                name=f"f106-da-pub-{suffix}",
                level=KnowledgeSpaceLevelEnum.PUBLIC,
                sort_weight=WEIGHT_BAND + 42_000,
                owner_type=KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
            )
            await session.execute(
                text(
                    """
                    INSERT INTO department_knowledge_space
                      (tenant_id, department_id, space_id, created_by)
                    VALUES
                      (1, :d1, :s1, 1),
                      (1, :d1, :s2, 1),
                      (1, :d2, :s3, 1)
                    """
                ),
                {
                    "d1": dept_id,
                    "s1": bound_team,
                    "s2": bound_ks,
                    "d2": other_id,
                    "s3": other_bound,
                },
            )
            await session.commit()
        space_ids = [bound_team, bound_ks, unbound, outsider, other_bound, public_a]
        dept_ids = [other_id, dept_id]
        fixture_ids.update(space_ids)
        admin_dept_ids.add(dept_id)

        async def _admin_ids(self):
            if int(self.login_user.user_id) == 88010603:
                return set(admin_dept_ids)
            return set()

        monkeypatch.setattr(KnowledgeSpaceService, "_admin_department_ids", _admin_ids)

        async def _visible_ids(*_args, **_kwargs):
            return [str(i) for i in fixture_ids]

        monkeypatch.setattr(
            "bisheng.permission.domain.services.permission_service.PermissionService.list_accessible_ids",
            _visible_ids,
        )

        app = _sort_app(_dept_admin_user())
        async with AsyncSession(engine, expire_on_commit=False) as session:
            outside_before = await _weights(session, [unbound, outsider, other_bound, public_a])

        ok = await _post_sort(app, bound_team, None, bound_ks)
        assert ok.json()["status_code"] == 200
        async with AsyncSession(engine, expire_on_commit=False) as session:
            bound_after = await _weights(session, [bound_team, bound_ks])
            outside_after = await _weights(session, [unbound, outsider, other_bound, public_a])
        assert bound_after[bound_team] is not None
        assert bound_after[bound_ks] is not None
        assert outside_after[unbound] == outside_before[unbound]
        assert outside_after[outsider] is None
        assert outside_after[other_bound] == outside_before[other_bound]
        assert outside_after[public_a] == outside_before[public_a]

        for space_id, prev, nxt in (
            (unbound, None, bound_team),
            (other_bound, None, bound_team),
            (public_a, None, None),
        ):
            denied = await _post_sort(app, space_id, prev, nxt)
            assert denied.json()["status_code"] == SpacePermissionDeniedError.Code
        async with AsyncSession(engine, expire_on_commit=False) as session:
            still = await _weights(session, [unbound, outsider, other_bound, public_a])
        assert still == outside_after
        denied_again = await _post_sort(app, unbound, None, bound_team)
        assert denied_again.json()["status_code"] == SpacePermissionDeniedError.Code
    finally:
        await _cleanup(engine, space_ids, dept_ids)
