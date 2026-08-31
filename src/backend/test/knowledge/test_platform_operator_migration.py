"""AT-22/23: 运营岗可全库迁移建批, 普通用户 403 且无脏行."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.repositories.interfaces.knowledge_migration_source_repository import (
    MigrationSpaceRecord,
)
from bisheng.knowledge.domain.services.knowledge_migration_service import (
    NormalizedBatchInput,
    require_system_admin,
)
from bisheng.user.domain.services.platform_operator import PLATFORM_OPERATOR_ROLE_NAME


def _ops_user(*, user_id: int = 88002001) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name="ops-migration-admin",
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
        role_names=[PLATFORM_OPERATOR_ROLE_NAME],
    )


def _plain_user(*, user_id: int = 88002002) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name="plain-migration-user",
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
        role_names=["普通用户"],
    )


def test_require_system_admin_allows_operator() -> None:
    ops = _ops_user()
    assert require_system_admin(ops) is ops
    assert ops.is_admin() is False


def test_require_system_admin_rejects_ordinary() -> None:
    with pytest.raises(HTTPException) as exc:
        require_system_admin(_plain_user())
    assert exc.value.status_code == 403


def test_require_system_admin_rejects_account_name_bypass() -> None:
    with pytest.raises(HTTPException) as exc:
        require_system_admin(
            SimpleNamespace(account="admin", is_admin=lambda: False, role_names=["管理员"])
        )
    assert exc.value.status_code == 403


def _mysql_async_url() -> str:
    override = os.environ.get("QA_EXPERT_FLOW_DATABASE_URL") or os.environ.get(
        "PLATFORM_OPERATOR_FLOW_DATABASE_URL"
    )
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


@pytest.fixture
async def mysql_engine():
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.core.database.connection import _patch_aiomysql_pre_ping

    set_current_tenant_id(1)
    _patch_aiomysql_pre_ping()
    engine = create_async_engine(_mysql_async_url(), pool_pre_ping=True)
    yield engine
    await engine.dispose()


def _normalized_input() -> NormalizedBatchInput:
    src = SimpleNamespace(id=91_000_101, name="ops-src-space", model="x")
    dst = SimpleNamespace(id=91_000_102, name="ops-dst-space", model="x")
    return NormalizedBatchInput(
        selections=[{"space_id": int(src.id), "nodes": [{"node_type": "file", "node_id": 1}]}],
        source_spaces=[
            MigrationSpaceRecord(space=src, level="public", owner_type="user", owner_id=1)
        ],
        target_space=MigrationSpaceRecord(
            space=dst, level="public", owner_type="user", owner_id=1
        ),
        target_folder_name=None,
        target_path="/",
    )


@pytest.mark.asyncio
async def test_ops_migration_flow_mysql(mysql_engine, monkeypatch):
    """U-ops GET 含非本人库; POST 落 knowledge_migration_batch; U-user 403 无新行."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from bisheng.common.dependencies.core_deps import get_db_session
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.core.database.connection import _patch_aiomysql_pre_ping
    from bisheng.knowledge.api.endpoints.knowledge_migration import router as migration_router
    from bisheng.knowledge.domain.services.knowledge_migration_service import (
        KnowledgeMigrationService,
    )

    _patch_aiomysql_pre_ping()
    engine = mysql_engine
    suffix = uuid.uuid4().hex[:8]
    ops = _ops_user(user_id=88_002_000 + (int(suffix[:6], 16) % 90_000))
    plain = _plain_user(user_id=ops.user_id + 1)
    auth: dict = {"user": ops}
    ops_request_id = f"ops-mig-{suffix}"
    user_request_id = f"user-mig-{suffix}"
    other_space_id = 91_000_201
    mine_space_id = 91_000_202

    async def patched_db():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    async def fake_list_spaces(self, *, keyword, level, offset, limit):
        del self, keyword, level, offset, limit
        # 与超管同一口径: 列表不按当前用户过滤, 含非本人库.
        return (
            [
                MigrationSpaceRecord(
                    space=SimpleNamespace(id=mine_space_id, name="mine-space"),
                    level="public",
                    owner_type="user",
                    owner_id=ops.user_id,
                ),
                MigrationSpaceRecord(
                    space=SimpleNamespace(id=other_space_id, name="other-owned"),
                    level="public",
                    owner_type="user",
                    owner_id=ops.user_id + 999,
                ),
            ],
            2,
        )

    async def fake_normalize(self, request):
        del self, request
        return _normalized_input()

    monkeypatch.setattr(
        "bisheng.knowledge.domain.repositories.implementations."
        "knowledge_migration_source_repository_impl.KnowledgeMigrationSourceRepositoryImpl.list_spaces",
        fake_list_spaces,
    )
    monkeypatch.setattr(KnowledgeMigrationService, "_normalize_create", fake_normalize)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_migration_service."
        "CeleryKnowledgeMigrationTaskDispatcher.dispatch_preflight",
        lambda self, batch_id: "ops-mig-preflight",
    )

    app = FastAPI()
    app.include_router(migration_router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: auth["user"]
    app.dependency_overrides[get_db_session] = patched_db

    create_body = {
        "request_id": ops_request_id,
        "source_selections": [{"space_id": 91_000_101, "nodes": [{"node_type": "file", "node_id": 1}]}],
        "target_space_id": 91_000_102,
        "preserve_structure": True,
        "conflict_strategy": "skip",
    }

    async def _count(session, request_id: str) -> int:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM knowledge_migration_batch "
                        "WHERE tenant_id = 1 AND request_id = :rid AND deleted_at IS NULL"
                    ),
                    {"rid": request_id},
                )
            ).scalar_one()
        )

    batch_no = None
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            spaces = await client.get("/api/v1/knowledge/migrations/spaces")
            body_spaces = spaces.json()
            assert spaces.status_code == 200
            assert body_spaces["status_code"] == 200, body_spaces
            space_ids = {int(item["id"]) for item in body_spaces["data"]["data"]}
            assert other_space_id in space_ids
            assert mine_space_id in space_ids

            created = await client.post("/api/v1/knowledge/migrations/batches", json=create_body)
            body_created = created.json()
            assert created.status_code == 200
            assert body_created["status_code"] == 200, body_created
            batch_no = body_created["data"]["batch_no"]
            assert body_created["data"]["operator_id"] == ops.user_id

            async with AsyncSession(engine, expire_on_commit=False) as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT operator_id, operator_name, request_id FROM knowledge_migration_batch "
                            "WHERE tenant_id = 1 AND batch_no = :bno AND deleted_at IS NULL"
                        ),
                        {"bno": batch_no},
                    )
                ).first()
                ops_count = await _count(session, ops_request_id)
            assert row is not None
            assert int(row[0]) == ops.user_id
            assert str(row[1]) == ops.user_name
            assert str(row[2]) == ops_request_id
            assert ops_count == 1

            again = await client.get(f"/api/v1/knowledge/migrations/batches/{batch_no}")
            body_again = again.json()
            assert again.status_code == 200
            assert body_again["status_code"] == 200, body_again
            assert body_again["data"]["batch_no"] == batch_no
            assert body_again["data"]["operator_id"] == ops.user_id

            auth["user"] = plain
            denied = await client.post(
                "/api/v1/knowledge/migrations/batches",
                json={**create_body, "request_id": user_request_id},
            )
            assert denied.status_code == 403

            spaces_denied = await client.get("/api/v1/knowledge/migrations/spaces")
            assert spaces_denied.status_code == 403

            async with AsyncSession(engine, expire_on_commit=False) as session:
                assert await _count(session, user_request_id) == 0
                assert await _count(session, ops_request_id) == 1
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                text(
                    "DELETE FROM knowledge_migration_batch "
                    "WHERE tenant_id = 1 AND request_id IN (:ops_rid, :user_rid)"
                ),
                {"ops_rid": ops_request_id, "user_rid": user_request_id},
            )
            await session.commit()
