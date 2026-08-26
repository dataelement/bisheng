# ruff: noqa: RUF002
"""IK9KP5：超管删未采纳回答并扣分后，账本与积分变动站内信必须同时落库。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.qa_expert import Answer, Question
from bisheng.points.domain.services.points_pending_deduct_service import (
    stable_deduct_idempotency_key,
)

PREFIX = "/api/v1/qa_experts"


def _ok(resp) -> dict:
    body = resp.json()
    assert resp.status_code == 200, body
    return body


async def _create_question(env, payload: dict) -> int:
    payload = {**payload, "title": env.t(payload["title"])}
    resp = await env.client.post(f"{PREFIX}/questions", json=payload)
    body = _ok(resp)
    assert body.get("status_code") == 200, body
    data = body.get("data") or {}
    if data.get("id"):
        return int(data["id"])
    row = await env.reload_row(Question, title=payload["title"])
    assert row is not None
    return int(row.id)


async def _create_answer(env, question_id: int, content: str) -> int:
    resp = await env.client.post(
        f"{PREFIX}/answers",
        json={"question_id": question_id, "content": content, "reveal_on_public": True},
    )
    body = _ok(resp)
    assert body.get("status_code") == 200, body
    data = body.get("data") or {}
    if data.get("id"):
        return int(data["id"])
    rows = await env.reload_all(Answer, question_id=question_id)
    assert rows
    return int(max(rows, key=lambda r: r.id).id)


async def _select_maps(engine, sql: str, params: dict) -> list[dict]:
    """按参数执行 SELECT，返回 mapping 列表。"""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        rows = (await session.execute(text(sql), params)).mappings().all()
        return [dict(row) for row in rows]


async def _cleanup_points_rows(engine, *, user_id: int, remark: str) -> None:
    """清掉本用例写入的积分流水、账户、补扣队列和站内信。"""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.execute(text("DELETE FROM user_point_log WHERE user_id = :u"), {"u": user_id})
        await session.execute(text("DELETE FROM user_point_account WHERE user_id = :u"), {"u": user_id})
        await session.execute(text("DELETE FROM point_pending_deduct WHERE user_id = :u"), {"u": user_id})
        await session.execute(
            text(
                "DELETE FROM inbox_message_read WHERE message_id IN "
                "(SELECT id FROM (SELECT id FROM inbox_message WHERE CAST(content AS CHAR) LIKE :p) t)"
            ),
            {"p": f"%{remark}%"},
        )
        await session.execute(
            text("DELETE FROM inbox_message WHERE CAST(content AS CHAR) LIKE :p"),
            {"p": f"%{remark}%"},
        )
        await session.commit()


async def test_moderate_delete_unadopted_answer_writes_log_and_inbox(flow_env, monkeypatch):
    """超管删未采纳回答并选 R1：user_point_log 扣分，inbox_message 发 points_changed；再删不得脏写。"""
    env = flow_env

    @asynccontextmanager
    async def patched_session():
        session = AsyncSession(bind=env.engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    monkeypatch.setattr(
        "bisheng.points.domain.services.points_pending_deduct_service.get_async_db_session",
        patched_session,
    )
    await env.seed_expert(user_id=201, name="被扣分专家")
    expert_uid = env.uid(201)
    remark = env.t("违规删除未采纳回答")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df删答扣分通知",
            "description": "未采纳回答",
            "business_domain": "steel",
            "question_type": "public",
        },
    )
    env.as_user(env.user(201, name="被扣分专家"))
    aid = await _create_answer(env, qid, "待删除未采纳回答")
    key = stable_deduct_idempotency_key("R1", "qa_answer", str(aid))

    rules = await _select_maps(
        env.engine,
        "SELECT rule_code, status, rule_type FROM point_rule WHERE tenant_id = 1 AND rule_code = 'R1'",
        {},
    )
    assert rules, "171 验收库缺少 R1 扣减规则"
    assert rules[0]["status"] == "enabled"
    assert rules[0]["rule_type"] == "deduct"

    try:
        env.as_user(env.user(501, name="super-admin", super_admin=True))
        body = _ok(
            await env.client.post(
                f"{PREFIX}/admin/moderate-delete",
                json={
                    "target_type": "answer",
                    "target_id": aid,
                    "rule_code": "R1",
                    "remark": remark,
                },
            )
        )
        assert body.get("status_code") == 200, body
        data = body.get("data") or {}
        assert data.get("deleted") is True
        assert data.get("deducted") is True
        assert data.get("target_user_id") == expert_uid

        logs = await _select_maps(
            env.engine,
            "SELECT id, user_id, delta, direction, rule_code, idempotency_key, remark "
            "FROM user_point_log WHERE idempotency_key = :k",
            {"k": key},
        )
        assert len(logs) == 1
        assert int(logs[0]["user_id"]) == expert_uid
        assert int(logs[0]["delta"]) < 0
        assert logs[0]["direction"] == "deduct"
        assert logs[0]["rule_code"] == "R1"

        inbox = await _select_maps(
            env.engine,
            "SELECT id, action_code, receiver, content FROM inbox_message "
            "WHERE action_code = 'points_changed' AND CAST(content AS CHAR) LIKE :p "
            "ORDER BY id",
            {"p": f"%{remark}%"},
        )
        assert len(inbox) == 1
        assert str(expert_uid) in str(inbox[0]["receiver"])
        content = str(inbox[0]["content"])
        assert "points_changed" in content
        assert "管理员为您扣减" in content or "deduct_admin" in content

        answer = await env.reload_row(Answer, id=aid)
        assert answer is not None
        assert int(answer.status) == 3

        again = _ok(
            await env.client.post(
                f"{PREFIX}/admin/moderate-delete",
                json={
                    "target_type": "answer",
                    "target_id": aid,
                    "rule_code": "R1",
                    "remark": remark,
                },
            )
        )
        assert again.get("status_code") != 200
        logs_after = await _select_maps(
            env.engine,
            "SELECT id FROM user_point_log WHERE idempotency_key = :k",
            {"k": key},
        )
        inbox_after = await _select_maps(
            env.engine,
            "SELECT id FROM inbox_message WHERE action_code = 'points_changed' AND CAST(content AS CHAR) LIKE :p",
            {"p": f"%{remark}%"},
        )
        assert len(logs_after) == 1
        assert len(inbox_after) == 1
    finally:
        await _cleanup_points_rows(env.engine, user_id=expert_uid, remark=remark)


async def test_moderate_delete_own_answered_question_skips_deduct(flow_env, monkeypatch):
    """超管删自己的已答问题：题被删、即使带 R1 也不写扣分流水；再删不得脏写。"""
    env = flow_env

    @asynccontextmanager
    async def patched_session():
        session = AsyncSession(bind=env.engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    monkeypatch.setattr(
        "bisheng.points.domain.services.points_pending_deduct_service.get_async_db_session",
        patched_session,
    )
    await env.seed_expert(user_id=201, name="回答专家")
    admin = env.user(501, name="super-admin", super_admin=True)
    admin_uid = env.uid(501)
    remark = env.t("超管自删已答问题")
    env.as_user(admin)
    qid = await _create_question(
        env,
        {
            "title": "df超管自删已答",
            "description": "已回答后锁定",
            "business_domain": "steel",
            "question_type": "public",
        },
    )
    env.as_user(env.user(201, name="回答专家"))
    await _create_answer(env, qid, "锁定用首答")
    locked = await env.reload_row(Question, id=qid)
    assert locked is not None
    assert int(locked.content_locked) == 1
    key = stable_deduct_idempotency_key("R1", "qa_question", str(qid))

    try:
        env.as_user(admin)
        body = _ok(
            await env.client.post(
                f"{PREFIX}/admin/moderate-delete",
                json={
                    "target_type": "question",
                    "target_id": qid,
                    "rule_code": "R1",
                    "remark": remark,
                },
            )
        )
        assert body.get("status_code") == 200, body
        data = body.get("data") or {}
        assert data.get("deleted") is True
        assert data.get("deducted") is False
        assert data.get("pending_deduct") is False
        assert data.get("reason") == "self_author"
        assert data.get("target_user_id") == admin_uid

        gone = await env.reload_row(Question, id=qid)
        assert gone is None

        logs = await _select_maps(
            env.engine,
            "SELECT id FROM user_point_log WHERE idempotency_key = :k OR (user_id = :u AND remark = :r)",
            {"k": key, "u": admin_uid, "r": remark},
        )
        pending = await _select_maps(
            env.engine,
            "SELECT id FROM point_pending_deduct WHERE user_id = :u",
            {"u": admin_uid},
        )
        assert logs == []
        assert pending == []

        again = _ok(
            await env.client.post(
                f"{PREFIX}/admin/moderate-delete",
                json={
                    "target_type": "question",
                    "target_id": qid,
                    "rule_code": "R1",
                    "remark": remark,
                },
            )
        )
        assert again.get("status_code") != 200
        logs_after = await _select_maps(
            env.engine,
            "SELECT id FROM user_point_log WHERE idempotency_key = :k OR (user_id = :u AND remark = :r)",
            {"k": key, "u": admin_uid, "r": remark},
        )
        pending_after = await _select_maps(
            env.engine,
            "SELECT id FROM point_pending_deduct WHERE user_id = :u",
            {"u": admin_uid},
        )
        assert logs_after == []
        assert pending_after == []
    finally:
        await _cleanup_points_rows(env.engine, user_id=admin_uid, remark=remark)
