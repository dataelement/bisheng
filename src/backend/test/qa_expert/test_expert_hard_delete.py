# ruff: noqa: RUF002
"""专家硬删与批量停用/删除流转测试。"""

from sqlalchemy import text

from bisheng.database.models.qa_expert import Answer, Expert, QuestionInvite
from bisheng.qa_expert.domain.repositories import AnswerRepository


async def test_hard_delete_removes_expert_row(flow_env):
    env = flow_env
    env.as_user(env.portal_admin)
    expert = await env.seed_expert(user_id=501, name="hard-del")
    expert_id = int(expert.id)

    resp = await env.client.post(f"/api/v1/qa_experts/experts/{expert_id}/delete")
    body = resp.json()
    assert body["status_code"] == 200

    row = await env.reload_row(Expert, id=expert_id)
    assert row is None


async def test_hard_delete_rejects_expert_with_answers(flow_env):
    env = flow_env
    env.as_user(env.portal_admin)
    expert = await env.seed_expert(user_id=502, name="has-answer")
    expert_id = int(expert.id)

    await AnswerRepository().create(
        Answer(
            tenant_id=1,
            question_id=999999,
            expert_id=expert_id,
            user_id=int(expert.user_id),
            expert_name=expert.expert_name,
            content="ans",
            status=1,
        )
    )

    resp = await env.client.post(f"/api/v1/qa_experts/experts/{expert_id}/delete")
    body = resp.json()
    assert body["status_code"] == 18314

    row = await env.reload_row(Expert, id=expert_id)
    assert row is not None

    async with env.engine.connect() as conn:
        await conn.execute(text("DELETE FROM qa_answer WHERE expert_id = :eid"), {"eid": expert_id})
        await conn.commit()


async def test_batch_disable_and_batch_delete(flow_env):
    env = flow_env
    env.as_user(env.portal_admin)
    a = await env.seed_expert(user_id=503, name="batch-a")
    b = await env.seed_expert(user_id=504, name="batch-b")
    c = await env.seed_expert(user_id=505, name="batch-c")
    ids = [int(a.id), int(b.id)]

    disable_resp = await env.client.post(
        "/api/v1/qa_experts/experts/batch-disable",
        json={"expert_ids": ids},
    )
    disable_body = disable_resp.json()
    assert disable_body["status_code"] == 200
    assert set(disable_body["data"]["succeeded"]) == set(ids)
    assert disable_body["data"]["failed"] == []

    for expert_id in ids:
        row = await env.reload_row(Expert, id=expert_id)
        assert int(row.status) == 0

    delete_ids = [int(a.id), int(c.id)]
    delete_resp = await env.client.post(
        "/api/v1/qa_experts/experts/batch-delete",
        json={"expert_ids": delete_ids},
    )
    delete_body = delete_resp.json()
    assert delete_body["status_code"] == 200
    assert set(delete_body["data"]["succeeded"]) == set(delete_ids)

    for expert_id in delete_ids:
        assert await env.reload_row(Expert, id=expert_id) is None

    remaining = await env.reload_row(Expert, id=int(b.id))
    assert remaining is not None


async def test_hard_delete_clears_invites(flow_env):
    env = flow_env
    env.as_user(env.portal_admin)
    expert = await env.seed_expert(user_id=506, name="invite-clean")
    expert_id = int(expert.id)

    async with env.engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO qa_question_invite (tenant_id, question_id, expert_id, user_id) "
                "VALUES (1, 999998, :eid, :uid)"
            ),
            {"eid": expert_id, "uid": int(expert.user_id)},
        )
        await conn.commit()

    resp = await env.client.post(f"/api/v1/qa_experts/experts/{expert_id}/delete")
    assert resp.json()["status_code"] == 200

    invites = await env.reload_all(QuestionInvite, expert_id=expert_id)
    assert invites == []
