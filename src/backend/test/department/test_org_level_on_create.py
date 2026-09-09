"""创建 / 移动后自动打 org_level: 171 MySQL 接口+落库流转 (无 DDL)."""

from __future__ import annotations

import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.core.database.connection import _patch_aiomysql_pre_ping
from bisheng.department.api.router import router as department_router


def _mysql_async_url() -> str:
    override = os.environ.get("QA_EXPERT_FLOW_DATABASE_URL") or os.environ.get("ORG_LEVEL_FLOW_DATABASE_URL")
    if override:
        return override.replace("pymysql", "aiomysql")
    from bisheng.core.config.settings import decrypt_token

    cfg_name = os.environ.get("config", "config.yaml")
    candidates = [
        Path(__file__).resolve().parents[2] / "bisheng" / Path(cfg_name).name,
        Path("/Users/lkk/workplace/bisheng/src/backend/bisheng") / Path(cfg_name).name,
    ]
    cfg_path = next((p for p in candidates if p.is_file()), None)
    if cfg_path is None:
        raise RuntimeError("找不到 config.yaml, 请设置 ORG_LEVEL_FLOW_DATABASE_URL")
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
        user_name="org-level-create-admin",
        tenant_id=1,
        is_admin=lambda: True,
        is_global_super=True,
        user_role=[1],
        role="admin",
    )


@pytest.fixture
async def flow_env(monkeypatch):
    """真实 MySQL session 注入到部门创建 / 移动 / org_level 查询."""
    set_current_tenant_id(1)
    _patch_aiomysql_pre_ping()
    engine = create_async_engine(_mysql_async_url(), pool_pre_ping=True)

    @asynccontextmanager
    async def patched_session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    monkeypatch.setattr(
        "bisheng.points.domain.services.department_org_level_service.get_async_db_session",
        patched_session,
    )
    monkeypatch.setattr(
        "bisheng.points.domain.services.department_org_level_labeler.get_async_db_session",
        patched_session,
    )
    monkeypatch.setattr(
        "bisheng.department.domain.services.department_service.get_async_db_session",
        patched_session,
    )
    monkeypatch.setattr(
        "bisheng.database.models.department.get_async_db_session",
        patched_session,
    )
    monkeypatch.setattr("bisheng.core.database.get_async_db_session", patched_session)
    monkeypatch.setattr(
        "bisheng.department.domain.services.department_service._get_dept_id_prefix",
        lambda: "BS",
    )
    monkeypatch.setattr(
        "bisheng.department.domain.services.department_service.DepartmentChangeHandler.execute_async",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.department.domain.services.department_root_guard.TenantDao.aget_by_id",
        AsyncMock(return_value=SimpleNamespace(root_dept_id=None)),
    )
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.knowledge_space_content."
        "KnowledgeSpaceContentStat.enqueue_department_stat_async",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.tenant.domain.services.user_tenant_sync_service.UserTenantSyncService.sync_subtree_primary_users",
        AsyncMock(return_value={"synced": [], "failed": []}),
    )

    yield engine
    await engine.dispose()


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(department_router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = _admin_user
    return app


async def _snapshot_and_clear_labels(session) -> list[tuple[int, str | None]]:
    rows = (
        await session.execute(
            text(
                "SELECT id, org_level FROM department "
                "WHERE tenant_id = 1 AND status = 'active' AND org_level IS NOT NULL"
            )
        )
    ).all()
    snapshot = [(int(r[0]), r[1]) for r in rows]
    if snapshot:
        await session.execute(
            text(
                "UPDATE department SET org_level = NULL "
                "WHERE tenant_id = 1 AND status = 'active' AND org_level IS NOT NULL"
            )
        )
    return snapshot


async def _restore_labels(session, snapshot: list[tuple[int, str | None]], dept_ids: list[str]) -> None:
    for dept_id in dept_ids:
        await session.execute(text("DELETE FROM department WHERE dept_id = :d"), {"d": dept_id})
    await session.execute(
        text(
            "UPDATE department SET org_level = NULL WHERE tenant_id = 1 AND status = 'active' AND org_level IS NOT NULL"
        )
    )
    for dept_pk, level in snapshot:
        await session.execute(
            text("UPDATE department SET org_level = :lv WHERE id = :id"),
            {"lv": level, "id": dept_pk},
        )
    await session.commit()


async def _insert_chain(session, suffix: str, *, with_company: bool) -> dict[str, object]:
    """插入 company/dept/office/squad 链, path 段数对齐相对深度."""
    ids = {
        "company": f"olc-co-{suffix}",
        "dept": f"olc-dept-{suffix}",
        "office": f"olc-off-{suffix}",
        "squad": f"olc-sq-{suffix}",
    }
    prefix = f"/olc-{suffix}"
    paths = {
        "company": f"{prefix}-c/",
        "dept": f"{prefix}-c/d/",
        "office": f"{prefix}-c/d/o/",
        "squad": f"{prefix}-c/d/o/s/",
    }
    await session.execute(
        text(
            """
            INSERT INTO department
              (dept_id, name, parent_id, tenant_id, path, status, source, org_level, is_deleted)
            VALUES
              (:co, :nco, NULL, 1, :pco, 'active', 'local', :lv_co, 0),
              (:de, :nde, NULL, 1, :pde, 'active', 'local', :lv_de, 0),
              (:of, :nof, NULL, 1, :pof, 'active', 'local', :lv_of, 0),
              (:sq, :nsq, NULL, 1, :psq, 'active', 'local', :lv_sq, 0)
            """
        ),
        {
            "co": ids["company"],
            "nco": f"olc-co-{suffix}",
            "pco": paths["company"],
            "lv_co": "company" if with_company else None,
            "de": ids["dept"],
            "nde": f"olc-dept-{suffix}",
            "pde": paths["dept"],
            "lv_de": "dept" if with_company else None,
            "of": ids["office"],
            "nof": f"olc-off-{suffix}",
            "pof": paths["office"],
            "lv_of": "office" if with_company else None,
            "sq": ids["squad"],
            "nsq": f"olc-sq-{suffix}",
            "psq": paths["squad"],
            "lv_sq": "squad" if with_company else None,
        },
    )
    await session.commit()
    pks = {}
    for key, dept_id in ids.items():
        pks[key] = (
            await session.execute(
                text("SELECT id FROM department WHERE dept_id = :d"),
                {"d": dept_id},
            )
        ).scalar_one()
    # 补 parent_id, 供 create / move 校验父节点存在
    await session.execute(
        text("UPDATE department SET parent_id = :pid WHERE dept_id = :d"),
        {"pid": pks["company"], "d": ids["dept"]},
    )
    await session.execute(
        text("UPDATE department SET parent_id = :pid WHERE dept_id = :d"),
        {"pid": pks["dept"], "d": ids["office"]},
    )
    await session.execute(
        text("UPDATE department SET parent_id = :pid WHERE dept_id = :d"),
        {"pid": pks["office"], "d": ids["squad"]},
    )
    await session.commit()
    return {"ids": ids, "pks": pks, "paths": paths}


async def _select_org_level(session, dept_id: str) -> str | None:
    return (
        await session.execute(
            text("SELECT org_level FROM department WHERE dept_id = :d"),
            {"d": dept_id},
        )
    ).scalar_one()


def _find_in_tree(nodes: list, dept_id: str) -> dict | None:
    for node in nodes:
        if node.get("dept_id") == dept_id:
            return node
        found = _find_in_tree(node.get("children") or [], dept_id)
        if found:
            return found
    return None


@pytest.mark.asyncio
async def test_create_under_office_labels_squad_and_get_returns_it(flow_env):
    """已有 company 根时, office 下新建落库 squad; GET org-levels / tree 仍返回 squad."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    created_dept_id = None
    snapshot: list[tuple[int, str | None]] = []
    fixture_ids: list[str] = []

    async with AsyncSession(engine, expire_on_commit=False) as session:
        snapshot = await _snapshot_and_clear_labels(session)
        chain = await _insert_chain(session, suffix, with_company=True)
        fixture_ids = list(chain["ids"].values())

    app = _app()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/departments/",
                json={"name": f"班组-{suffix}", "parent_id": chain["pks"]["office"]},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status_code"] == 200
            created = body["data"]
            created_dept_id = created["dept_id"]
            assert created["org_level"] == "squad"

            async with AsyncSession(engine, expire_on_commit=False) as session:
                db_level = await _select_org_level(session, created_dept_id)
            assert db_level == "squad"

            levels = await client.get("/api/v1/departments/org-levels")
            assert levels.status_code == 200
            level_rows = levels.json()["data"]
            created_row = next(r for r in level_rows if r["dept_id"] == created_dept_id)
            assert created_row["org_level"] == "squad"

            tree = await client.get("/api/v1/departments/tree")
            assert tree.status_code == 200
            tree_node = _find_in_tree(tree.json()["data"], created_dept_id)
            assert tree_node is not None
            assert tree_node["org_level"] == "squad"
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            extra = [created_dept_id] if created_dept_id else []
            await _restore_labels(session, snapshot, fixture_ids + extra)


@pytest.mark.asyncio
async def test_create_without_company_root_keeps_null(flow_env):
    """无 company 根时新建 org_level 仍为 NULL."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    created_dept_id = None
    snapshot: list[tuple[int, str | None]] = []
    fixture_ids: list[str] = []

    async with AsyncSession(engine, expire_on_commit=False) as session:
        snapshot = await _snapshot_and_clear_labels(session)
        chain = await _insert_chain(session, suffix, with_company=False)
        fixture_ids = list(chain["ids"].values())

    app = _app()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/departments/",
                json={"name": f"未标-{suffix}", "parent_id": chain["pks"]["office"]},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status_code"] == 200
            created_dept_id = body["data"]["dept_id"]
            assert body["data"]["org_level"] is None

            async with AsyncSession(engine, expire_on_commit=False) as session:
                db_level = await _select_org_level(session, created_dept_id)
            assert db_level is None
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            extra = [created_dept_id] if created_dept_id else []
            await _restore_labels(session, snapshot, fixture_ids + extra)


@pytest.mark.asyncio
async def test_create_under_squad_still_writes_squad(flow_env):
    """班组下再新建落库仍为 squad (展示层藏徽章, 库值不变)."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    created_dept_id = None
    snapshot: list[tuple[int, str | None]] = []
    fixture_ids: list[str] = []

    async with AsyncSession(engine, expire_on_commit=False) as session:
        snapshot = await _snapshot_and_clear_labels(session)
        chain = await _insert_chain(session, suffix, with_company=True)
        fixture_ids = list(chain["ids"].values())

    app = _app()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/departments/",
                json={"name": f"下层-{suffix}", "parent_id": chain["pks"]["squad"]},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status_code"] == 200
            created_dept_id = body["data"]["dept_id"]
            assert body["data"]["org_level"] == "squad"

            async with AsyncSession(engine, expire_on_commit=False) as session:
                db_level = await _select_org_level(session, created_dept_id)
            assert db_level == "squad"
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            extra = [created_dept_id] if created_dept_id else []
            await _restore_labels(session, snapshot, fixture_ids + extra)


@pytest.mark.asyncio
async def test_move_squad_under_company_relabels_to_dept(flow_env):
    """squad 从 office 挪到 company 下, 按相对深度重算为 dept."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    snapshot: list[tuple[int, str | None]] = []
    fixture_ids: list[str] = []

    async with AsyncSession(engine, expire_on_commit=False) as session:
        snapshot = await _snapshot_and_clear_labels(session)
        chain = await _insert_chain(session, suffix, with_company=True)
        fixture_ids = list(chain["ids"].values())

    app = _app()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                before = await _select_org_level(session, chain["ids"]["squad"])
            assert before == "squad"

            resp = await client.post(
                f"/api/v1/departments/{chain['ids']['squad']}/move",
                json={"new_parent_id": chain["pks"]["company"]},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status_code"] == 200
            assert body["data"]["org_level"] == "dept"

            async with AsyncSession(engine, expire_on_commit=False) as session:
                after = await _select_org_level(session, chain["ids"]["squad"])
            assert after == "dept"

            again = await client.get(f"/api/v1/departments/{chain['ids']['squad']}")
            assert again.status_code == 200
            assert again.json()["data"]["org_level"] == "dept"
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await _restore_labels(session, snapshot, fixture_ids)


@pytest.mark.asyncio
async def test_create_invalid_parent_rejects_without_dirty_label(flow_env):
    """父部门不存在时拒绝创建, 且不写入脏标签行."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    snapshot: list[tuple[int, str | None]] = []
    name = f"脏标-{suffix}"

    async with AsyncSession(engine, expire_on_commit=False) as session:
        snapshot = await _snapshot_and_clear_labels(session)

    app = _app()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/departments/",
                json={"name": name, "parent_id": 9_999_999_001},
            )
            assert resp.status_code == 200
            assert resp.json()["status_code"] == 21000

            async with AsyncSession(engine, expire_on_commit=False) as session:
                leftover = (
                    await session.execute(
                        text("SELECT id, org_level FROM department WHERE name = :n"),
                        {"n": name},
                    )
                ).all()
            assert leftover == []
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(text("DELETE FROM department WHERE name = :n"), {"n": name})
            await _restore_labels(session, snapshot, [])
