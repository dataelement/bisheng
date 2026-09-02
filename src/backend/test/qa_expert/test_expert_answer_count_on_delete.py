"""作者删未采纳回答: qa_expert.answer_count 减 1, 采纳数不变; 拒绝路径不改计数。"""

from __future__ import annotations

from bisheng.database.models.qa_expert import Answer, Expert, Question

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
    qid = data.get("id")
    if qid:
        return int(qid)
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
    aid = data.get("id")
    if aid:
        return int(aid)
    rows = await env.reload_all(Answer, question_id=question_id)
    assert rows
    return int(max(rows, key=lambda r: r.id).id)


async def _expert_by_user_api(env, user_id: int) -> dict:
    """再读一枪: GET 专家档案, 核对接口与落库一致。"""
    body = _ok(await env.client.get(f"{PREFIX}/experts/userid/{user_id}"))
    assert body.get("status_code") == 200, body
    data = body.get("data") or {}
    if hasattr(data, "answer_count"):
        return {
            "answer_count": int(data.answer_count or 0),
            "adoption_count": int(data.adoption_count or 0),
        }
    return {
        "answer_count": int(data.get("answer_count") or 0),
        "adoption_count": int(data.get("adoption_count") or 0),
    }


async def test_author_delete_unadopted_decrements_expert_answer_count(flow_env):
    """两答一采纳, 删未采纳: 回答数 2→1, 采纳数仍 1; 再删同一条拒绝且计数不变。"""
    env = flow_env
    expert = await env.seed_expert(user_id=201, name="专家甲")
    expert_uid = env.uid(201)
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "删答回退专家计数",
            "description": "公开",
            "business_domain": "steel",
            "question_type": "public",
        },
    )
    env.as_user(env.user(201, name="专家甲"))
    keep_aid = await _create_answer(env, qid, "将被采纳")
    drop_aid = await _create_answer(env, qid, "未采纳可删")
    env.as_user(env.asker)
    adopted = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": keep_aid}))
    assert adopted.get("status_code") == 200, adopted

    before = await env.reload_row(Expert, id=int(expert.id))
    assert int(before.answer_count) == 2
    assert int(before.adoption_count) == 1

    env.as_user(env.user(201, name="专家甲"))
    deleted = _ok(await env.client.delete(f"{PREFIX}/answers/{drop_aid}"))
    assert deleted.get("status_code") == 200, deleted

    stored_answer = await env.reload_row(Answer, id=drop_aid)
    assert int(stored_answer.status) == 3
    stored_question = await env.reload_row(Question, id=qid)
    assert int(stored_question.answer_count) == 1
    stored_expert = await env.reload_row(Expert, id=int(expert.id))
    assert int(stored_expert.answer_count) == 1
    assert int(stored_expert.adoption_count) == 1

    api = await _expert_by_user_api(env, expert_uid)
    assert api["answer_count"] == 1
    assert api["adoption_count"] == 1

    again = _ok(await env.client.delete(f"{PREFIX}/answers/{drop_aid}"))
    assert again.get("status_code") != 200
    stored_again = await env.reload_row(Expert, id=int(expert.id))
    assert int(stored_again.answer_count) == 1
    assert int(stored_again.adoption_count) == 1
    api_again = await _expert_by_user_api(env, expert_uid)
    assert api_again["answer_count"] == 1
    assert int((await env.reload_row(Question, id=qid)).answer_count) == 1


async def test_author_cannot_delete_adopted_leaves_expert_counts(flow_env):
    """已采纳拒绝删除: qa_expert.answer_count / adoption_count 均不变。"""
    env = flow_env
    expert = await env.seed_expert(user_id=201, name="专家甲")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "已采纳不回退计数",
            "description": "公开",
            "business_domain": "steel",
            "question_type": "public",
        },
    )
    env.as_user(env.user(201, name="专家甲"))
    aid = await _create_answer(env, qid, "唯一采纳")
    env.as_user(env.asker)
    adopted = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": aid}))
    assert adopted.get("status_code") == 200, adopted
    before = await env.reload_row(Expert, id=int(expert.id))
    assert int(before.answer_count) == 1
    assert int(before.adoption_count) == 1

    env.as_user(env.user(201, name="专家甲"))
    denied = _ok(await env.client.delete(f"{PREFIX}/answers/{aid}"))
    assert denied.get("status_code") == 18312
    after = await env.reload_row(Expert, id=int(expert.id))
    assert int(after.answer_count) == 1
    assert int(after.adoption_count) == 1
    still = await env.reload_row(Answer, id=aid)
    assert int(still.status) != 3
    assert bool(still.adopted)
    api = await _expert_by_user_api(env, env.uid(201))
    assert api["answer_count"] == 1
    assert api["adoption_count"] == 1
