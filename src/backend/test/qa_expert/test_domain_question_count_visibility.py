"""业务域问题数只统计当前用户可见的问题, 与列表同一套范围."""

from bisheng.database.models.qa_expert import Question, QuestionInvite

PREFIX = "/api/v1/qa_experts"


def _ok(resp) -> dict:
    body = resp.json()
    assert resp.status_code == 200, body
    return body


def _count_for(body: dict, domain: str) -> int:
    rows = body.get("data") or []
    matched = [row for row in rows if row.get("business_domain") == domain]
    assert len(matched) == 1, rows
    return int(matched[0].get("answer_count") or 0)


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


async def _domain_count(env, domain: str) -> int:
    body = _ok(await env.client.get(f"{PREFIX}/questions/answer_count/domain"))
    assert body.get("status_code") == 200, body
    return _count_for(body, domain)


async def _list_total(env, domain: str) -> int:
    body = _ok(await env.client.get(f"{PREFIX}/questions", params={"domain": domain, "page": 1, "page_size": 20}))
    assert body.get("status_code") == 200, body
    data = body.get("data") or {}
    return int(data.get("total") or 0)


async def test_domain_question_count_follows_visibility(flow_env):
    """路人看不到别人的定向题, 业务域计数与列表总数都不含它; 提问者和受邀专家含它."""
    env = flow_env
    domain = env.t("域可见计数")
    expert = await env.seed_expert(user_id=201, name="域计数专家")
    env.as_user(env.asker)
    public_id = await _create_question(
        env,
        {
            "title": "域计数公开题",
            "description": "公开",
            "business_domain": domain,
            "question_type": "public",
        },
    )
    directed_id = await _create_question(
        env,
        {
            "title": "域计数定向题",
            "description": "定向",
            "business_domain": domain,
            "question_type": "directed",
            "invited_expert_ids": [expert.id],
            "asker_reveal_on_public": True,
        },
    )
    invites = await env.reload_all(QuestionInvite, question_id=directed_id)
    assert {int(row.user_id) for row in invites} == {env.uid(201)}

    env.as_user(env.stranger)
    assert await _domain_count(env, domain) == 1
    assert await _list_total(env, domain) == 1
    again = await _domain_count(env, domain)
    assert again == 1
    stored = await env.reload_all(Question, business_domain=domain)
    stored_ids = {int(row.id) for row in stored}
    assert public_id in stored_ids
    assert directed_id in stored_ids

    env.as_user(env.asker)
    assert await _domain_count(env, domain) == 2
    assert await _list_total(env, domain) == 2

    env.as_user(env.user(201, name="域计数专家"))
    assert await _domain_count(env, domain) == 2
    assert await _list_total(env, domain) == 2

    env.as_user(env.portal_admin)
    assert await _domain_count(env, domain) == 2
    assert await _list_total(env, domain) == 2
