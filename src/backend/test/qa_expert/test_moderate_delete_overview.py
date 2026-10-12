"""超管删除专家回答后, 问题详情状态与按专家名查询必须跟着剩余回答变."""

from bisheng.database.models.qa_expert import Answer, AnswerAdopt, Expert, Question

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
    return int(max(rows, key=lambda row: row.id).id)


async def _detail(env, question_id: int) -> dict:
    body = _ok(await env.client.get(f"{PREFIX}/questions/{question_id}"))
    assert body.get("status_code") == 200, body
    return body.get("data") or {}


async def _answer_by_expert(env, question_id: int, expert_name: str):
    body = _ok(
        await env.client.get(
            f"{PREFIX}/questions/{question_id}/answers",
            params={"expert_name": expert_name},
        )
    )
    assert body.get("status_code") == 200, body
    return body.get("data")


async def _moderate_delete(env, answer_id: int) -> dict:
    env.as_user(env.user(501, name="super-admin", super_admin=True))
    return _ok(
        await env.client.post(
            f"{PREFIX}/admin/moderate-delete",
            json={"target_type": "answer", "target_id": answer_id},
        )
    )


async def test_moderate_delete_last_answer_resets_overview(flow_env):
    """删掉唯一未采纳回答: 详情变为未回答, 按专家名查不到, 再删不改计数."""
    env = flow_env
    expert = await env.seed_expert(user_id=201, name="概况专家甲")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "概况删最后一答",
            "description": "定向",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [expert.id],
            "asker_reveal_on_public": True,
        },
    )
    env.as_user(env.user(201, name="概况专家甲"))
    aid = await _create_answer(env, qid, "唯一回答")

    env.as_user(env.asker)
    before = await _detail(env, qid)
    assert before.get("display_status") == "pending_adopt"
    assert int(before.get("answer_count") or 0) == 1
    found = await _answer_by_expert(env, qid, expert.expert_name)
    assert found is not None
    assert int(found.get("id")) == aid

    deleted = await _moderate_delete(env, aid)
    assert deleted.get("status_code") == 200, deleted
    assert (deleted.get("data") or {}).get("deleted") is True

    env.as_user(env.asker)
    after = await _detail(env, qid)
    assert after.get("display_status") == "unanswered"
    assert int(after.get("answer_count") or 0) == 0
    assert int(after.get("adopt_count") or 0) == 0
    assert await _answer_by_expert(env, qid, expert.expert_name) is None

    question = await env.reload_row(Question, id=qid)
    answer = await env.reload_row(Answer, id=aid)
    stored_expert = await env.reload_row(Expert, id=expert.id)
    assert int(question.answer_count) == 0
    assert int(question.adopt_count) == 0
    assert int(question.status) == 0
    assert answer.status == 3
    assert int(stored_expert.answer_count) == 0

    again = await _moderate_delete(env, aid)
    assert again.get("status_code") == 10903
    question_again = await env.reload_row(Question, id=qid)
    expert_again = await env.reload_row(Expert, id=expert.id)
    assert int(question_again.answer_count) == 0
    assert int(question_again.adopt_count) == 0
    assert int(expert_again.answer_count) == 0


async def test_moderate_delete_adopted_answer_reopens_pending(flow_env):
    """删掉唯一已采纳回答, 同题还有未采纳回答: 状态回到待采纳, 该专家不再算已回答."""
    env = flow_env
    expert_a = await env.seed_expert(user_id=201, name="概况专家甲")
    expert_b = await env.seed_expert(user_id=202, name="概况专家乙")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "概况删已采纳",
            "description": "定向",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [expert_a.id, expert_b.id],
            "asker_reveal_on_public": True,
        },
    )
    env.as_user(env.user(201, name="概况专家甲"))
    aid = await _create_answer(env, qid, "被采纳的回答")
    env.as_user(env.user(202, name="概况专家乙"))
    bid = await _create_answer(env, qid, "未采纳的回答")
    env.as_user(env.asker)
    adopt = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": aid}))
    assert adopt.get("status_code") == 200, adopt

    solved = await _detail(env, qid)
    assert solved.get("display_status") == "solved"
    assert int(solved.get("adopt_count") or 0) == 1

    deleted = await _moderate_delete(env, aid)
    assert deleted.get("status_code") == 200, deleted

    env.as_user(env.asker)
    after = await _detail(env, qid)
    assert after.get("display_status") == "pending_adopt"
    assert int(after.get("answer_count") or 0) == 1
    assert int(after.get("adopt_count") or 0) == 0
    assert after.get("adopted_answer_id") in (None, 0)
    assert await _answer_by_expert(env, qid, expert_a.expert_name) is None
    remaining = await _answer_by_expert(env, qid, expert_b.expert_name)
    assert remaining is not None
    assert int(remaining.get("id")) == bid

    question = await env.reload_row(Question, id=qid)
    adopts = await env.reload_all(AnswerAdopt, question_id=qid)
    expert_row = await env.reload_row(Expert, id=expert_a.id)
    other_row = await env.reload_row(Expert, id=expert_b.id)
    assert int(question.answer_count) == 1
    assert int(question.adopt_count) == 0
    assert int(question.status) == 0
    assert question.adopted_answer_id in (None, 0)
    assert adopts == []
    assert int(expert_row.answer_count) == 0
    assert int(expert_row.adoption_count) == 0
    assert int(other_row.answer_count) == 1
    assert int(other_row.adoption_count) == 0

    again = await _moderate_delete(env, aid)
    assert again.get("status_code") == 10903
    question_again = await env.reload_row(Question, id=qid)
    expert_again = await env.reload_row(Expert, id=expert_a.id)
    assert int(question_again.answer_count) == 1
    assert int(question_again.adopt_count) == 0
    assert int(expert_again.answer_count) == 0
    assert int(expert_again.adoption_count) == 0


async def test_moderate_delete_one_adopted_keeps_solved(flow_env):
    """两条都已采纳时删一条: 状态仍是已解决, 被删专家查不到, 另一条采纳槽还在."""
    env = flow_env
    expert_a = await env.seed_expert(user_id=201, name="概况专家甲")
    expert_b = await env.seed_expert(user_id=202, name="概况专家乙")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "概况删一条采纳",
            "description": "定向",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [expert_a.id, expert_b.id],
            "asker_reveal_on_public": True,
        },
    )
    env.as_user(env.user(201, name="概况专家甲"))
    aid = await _create_answer(env, qid, "采纳甲")
    env.as_user(env.user(202, name="概况专家乙"))
    bid = await _create_answer(env, qid, "采纳乙")
    env.as_user(env.asker)
    first = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": aid}))
    second = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": bid}))
    assert first.get("status_code") == 200, first
    assert second.get("status_code") == 200, second

    deleted = await _moderate_delete(env, aid)
    assert deleted.get("status_code") == 200, deleted

    env.as_user(env.asker)
    after = await _detail(env, qid)
    assert after.get("display_status") == "solved"
    assert int(after.get("answer_count") or 0) == 1
    assert int(after.get("adopt_count") or 0) == 1
    assert int(after.get("adopted_answer_id") or 0) == bid
    assert await _answer_by_expert(env, qid, expert_a.expert_name) is None
    kept = await _answer_by_expert(env, qid, expert_b.expert_name)
    assert kept is not None
    assert int(kept.get("id")) == bid

    question = await env.reload_row(Question, id=qid)
    adopts = await env.reload_all(AnswerAdopt, question_id=qid)
    assert int(question.status) == 1
    assert int(question.adopt_count) == 1
    assert int(question.adopted_answer_id) == bid
    assert {int(row.answer_id) for row in adopts} == {bid}

    again = await _moderate_delete(env, aid)
    assert again.get("status_code") == 10903
    question_again = await env.reload_row(Question, id=qid)
    adopts_again = await env.reload_all(AnswerAdopt, question_id=qid)
    assert int(question_again.adopt_count) == 1
    assert int(question_again.adopted_answer_id) == bid
    assert {int(row.answer_id) for row in adopts_again} == {bid}
