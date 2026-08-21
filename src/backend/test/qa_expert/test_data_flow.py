# ruff: noqa: RUF002
"""F083 接口+落库流转：对照 api-data-flow-matrix.md P0。仓储不 mock。"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.utils.beijing_time import now_beijing
from bisheng.database.models.qa_expert import (
    AnonymousAlias,
    Answer,
    AnswerAdopt,
    AnswerEligibility,
    Comment,
    Expert,
    PublishApprover,
    PublishRequest,
    Question,
    QuestionInvite,
)
from bisheng.qa_expert.domain.services import CommentService

PREFIX = "/api/v1/qa_experts"
_REAL_SEND_COMMENT_NOTIFICATION = CommentService._send_comment_notification


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


async def _create_answer_anonymous(env, question_id: int, content: str, *, reveal_on_public: bool | None = None) -> int:
    payload: dict = {"question_id": question_id, "content": content, "anonymous": True}
    if reveal_on_public is not None:
        payload["reveal_on_public"] = reveal_on_public
    resp = await env.client.post(f"{PREFIX}/answers", json=payload)
    body = _ok(resp)
    assert body.get("status_code") == 200, body
    data = body.get("data") or {}
    aid = data.get("id")
    if aid:
        return int(aid)
    rows = await env.reload_all(Answer, question_id=question_id)
    assert rows
    return int(max(rows, key=lambda r: r.id).id)


async def test_df01_directed_persists_question_and_invite(flow_env):
    env = flow_env
    expert = await env.seed_expert(user_id=201, name="专家甲")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df01定向题",
            "description": "定向正文",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [expert.id],
            "asker_reveal_on_public": True,
        },
    )
    question = await env.reload_row(Question, id=qid)
    invites = await env.reload_all(QuestionInvite, question_id=qid)
    assert question.question_type == "directed"
    assert question.content_locked == 0
    assert len(invites) == 1
    assert invites[0].user_id == env.uid(201)
    assert invites[0].expert_id == expert.id
    assert question.experts_names == expert.expert_name
    assert question.experts_names != str(expert.id)
    detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    assert detail["status_code"] == 200
    data = detail.get("data") or {}
    assert data.get("experts_names") == expert.expert_name
    assert data.get("experts_names") != str(expert.id)
    assert "定向正文" in str(data)
    again = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    assert (again.get("data") or {}).get("experts_names") == expert.expert_name


async def test_df02_public_visible_to_stranger(flow_env):
    env = flow_env
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {"title": "df02公开题", "description": "公开正文", "business_domain": "steel", "question_type": "public"},
    )
    question = await env.reload_row(Question, id=qid)
    invites = await env.reload_all(QuestionInvite, question_id=qid)
    assert question.question_type == "public"
    assert invites == []
    env.as_user(env.stranger)
    detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    assert detail["status_code"] == 200
    assert "公开正文" in str(detail.get("data"))


async def test_df03_directed_denied_no_leak_and_absent_from_list(flow_env):
    env = flow_env
    expert = await env.seed_expert(user_id=201, name="专家甲")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df03机密标题",
            "description": "机密正文",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [expert.id],
            "asker_reveal_on_public": False,
        },
    )
    env.as_user(env.stranger)
    detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    assert detail["status_code"] == 18301
    dumped = str(detail)
    assert "机密标题" not in dumped
    assert "机密正文" not in dumped
    listed = _ok(
        await env.client.get(
            f"{PREFIX}/questions",
            params={"page": 1, "page_size": 50, "keyword": env.t("df03机密标题")},
        )
    )
    assert listed["status_code"] == 200
    questions = (listed.get("data") or {}).get("questions") or []
    ids = {int(item["id"]) for item in questions if isinstance(item, dict) and item.get("id")}
    assert qid not in ids
    assert await env.reload_row(Question, id=qid) is not None


async def test_df04_related_docs_persisted_as_space_file_id(flow_env):
    env = flow_env
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df04关联文档",
            "description": "正文仍在",
            "business_domain": "steel",
            "question_type": "public",
            "related_doc_ids": ["3-8"],
        },
    )
    question = await env.reload_row(Question, id=qid)
    assert question.related_docs
    assert "3-8" in question.related_docs
    detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    assert detail["status_code"] == 200
    data = detail.get("data") or {}
    views = data.get("related_doc_views") or data.get("related_docs") or []
    if isinstance(views, list) and views and isinstance(views[0], dict):
        assert views[0].get("unavailable_reason") == "forbidden"
        assert views[0].get("unavailable_reason") != "not_found"
    assert "正文仍在" in str(data)


async def test_df04b_related_docs_follow_space_read_not_asker(flow_env, monkeypatch):
    """落库 related_docs 后，可点链接跟知识空间 can_read，不跟提问者身份。"""
    from bisheng.qa_expert.domain import related_docs_access as related_docs_access_mod

    env = flow_env
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df04b权限切开",
            "description": "正文仍在",
            "business_domain": "steel",
            "question_type": "public",
            "related_doc_ids": ["8-15", "8-16"],
        },
    )
    stored = await env.reload_row(Question, id=qid)
    assert stored.related_docs
    assert "8-15" in stored.related_docs

    monkeypatch.setattr(related_docs_access_mod, "_file_belongs_to_space", AsyncMock(return_value=True))

    async def fake_check(*, user_id, relation, object_type, object_id, login_user=None):
        assert relation == "can_read"
        assert object_type == "knowledge_space"
        assert object_id == "8"
        return int(user_id) == int(env.stranger.user_id)

    monkeypatch.setattr(
        "bisheng.permission.domain.services.permission_service.PermissionService.check",
        fake_check,
    )

    async def live_check(user, space_id, file_id, *, space_cache=None):
        if not await related_docs_access_mod._file_belongs_to_space(int(space_id), int(file_id)):
            return None
        cache_key = int(space_id)
        if space_cache is not None and cache_key in space_cache:
            return space_cache[cache_key]
        allowed = await related_docs_access_mod._space_can_read(user, cache_key)
        if space_cache is not None:
            space_cache[cache_key] = allowed
        return allowed

    monkeypatch.setattr(
        "bisheng.qa_expert.domain.related_docs_access.check_related_doc_access",
        live_check,
    )

    asker_detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    assert asker_detail["status_code"] == 200
    asker_views = (asker_detail.get("data") or {}).get("related_doc_views") or []
    assert asker_views
    assert all(item.get("accessible") is False for item in asker_views)
    assert all(item.get("unavailable_reason") == "forbidden" for item in asker_views)

    env.as_user(env.stranger)
    stranger_detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    assert stranger_detail["status_code"] == 200
    stranger_views = (stranger_detail.get("data") or {}).get("related_doc_views") or []
    assert len(stranger_views) == 2
    assert all(item.get("accessible") is True for item in stranger_views)
    again = await env.reload_row(Question, id=qid)
    assert "8-15" in again.related_docs
    env.as_user(env.asker)
    asker_again = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    asker_views_again = (asker_again.get("data") or {}).get("related_doc_views") or []
    assert all(item.get("accessible") is False for item in asker_views_again)


async def test_df04c_favorite_reference_rewrites_to_source_file(flow_env, monkeypatch):
    """从「我的收藏」选文档后，qa_question.related_docs 与详情链接必须指向源文件。"""
    from bisheng.knowledge.domain.models.knowledge_file import (
        FileType,
        KnowledgeFile,
        KnowledgeFileStatus,
    )
    from bisheng.qa_expert.domain import related_docs_access as related_docs_access_mod

    env = flow_env
    src_space_id = 88_100_000 + (env.asker.user_id % 9000)
    fav_space_id = src_space_id + 1
    src_file_id = 0
    fav_file_id = 0
    async with AsyncSession(env.engine, expire_on_commit=False) as session:
        src_file = KnowledgeFile(
            tenant_id=1,
            knowledge_id=src_space_id,
            user_id=env.asker.user_id,
            file_name=f"{env.prefix}src-规程.pdf",
            file_type=FileType.FILE.value,
            file_source="upload",
            status=KnowledgeFileStatus.SUCCESS.value,
            object_name=f"{env.prefix}src-object",
        )
        session.add(src_file)
        await session.flush()
        fav_file = KnowledgeFile(
            tenant_id=1,
            knowledge_id=fav_space_id,
            user_id=env.asker.user_id,
            file_name=f"{env.prefix}fav-规程.pdf",
            file_type=FileType.FILE.value,
            file_source="favorite_reference",
            status=KnowledgeFileStatus.SUCCESS.value,
            user_metadata={
                "favorite_reference": {
                    "source_space_id": src_space_id,
                    "source_file_id": int(src_file.id),
                }
            },
        )
        session.add(fav_file)
        await session.commit()
        await session.refresh(src_file)
        await session.refresh(fav_file)
        src_file_id = int(src_file.id)
        fav_file_id = int(fav_file.id)
    fav_token = f"{fav_space_id}-{fav_file_id}"
    src_token = f"{src_space_id}-{src_file_id}"

    async def fake_check(*, user_id, relation, object_type, object_id, login_user=None):
        assert relation == "can_read"
        assert object_type == "knowledge_space"
        return int(object_id) == int(src_space_id) and int(user_id) == int(env.asker.user_id)

    monkeypatch.setattr(
        "bisheng.permission.domain.services.permission_service.PermissionService.check",
        fake_check,
    )

    async def live_check(user, space_id, file_id, *, space_cache=None):
        if not await related_docs_access_mod._file_belongs_to_space(int(space_id), int(file_id)):
            return None
        cache_key = int(space_id)
        if space_cache is not None and cache_key in space_cache:
            return space_cache[cache_key]
        allowed = await related_docs_access_mod._space_can_read(user, cache_key)
        if space_cache is not None:
            space_cache[cache_key] = allowed
        return allowed

    monkeypatch.setattr(
        "bisheng.qa_expert.domain.related_docs_access.check_related_doc_access",
        live_check,
    )

    try:
        env.as_user(env.asker)
        qid = await _create_question(
            env,
            {
                "title": "df04c收藏关联",
                "description": "收藏文档正文",
                "business_domain": "steel",
                "question_type": "public",
                "related_doc_ids": [fav_token],
            },
        )
        stored = await env.reload_row(Question, id=qid)
        assert stored.related_docs == src_token
        assert fav_token not in (stored.related_docs or "")

        asker_detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
        assert asker_detail["status_code"] == 200
        asker_views = (asker_detail.get("data") or {}).get("related_doc_views") or []
        assert len(asker_views) == 1
        assert asker_views[0].get("accessible") is True
        assert asker_views[0].get("space_id") == src_space_id
        assert asker_views[0].get("file_id") == src_file_id
        assert asker_views[0].get("id") == src_token
        assert "收藏文档正文" in str(asker_detail.get("data") or {})

        env.as_user(env.stranger)
        stranger_detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
        stranger_views = (stranger_detail.get("data") or {}).get("related_doc_views") or []
        assert len(stranger_views) == 1
        assert stranger_views[0].get("accessible") is False
        assert stranger_views[0].get("unavailable_reason") == "forbidden"

        again = await env.reload_row(Question, id=qid)
        assert again.related_docs == src_token

        env.as_user(env.asker)
        asker_again = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
        asker_views_again = (asker_again.get("data") or {}).get("related_doc_views") or []
        assert asker_views_again[0].get("accessible") is True
        assert asker_views_again[0].get("space_id") == src_space_id
    finally:
        async with AsyncSession(env.engine, expire_on_commit=False) as session:
            await session.execute(
                text("DELETE FROM knowledgefile WHERE file_name LIKE :p"),
                {"p": f"{env.prefix}%"},
            )
            await session.commit()


async def test_df05_first_answer_locks_content(flow_env):
    env = flow_env
    expert = await env.seed_expert(user_id=201, name="专家甲")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df05首答锁",
            "description": "原正文",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [expert.id],
            "asker_reveal_on_public": True,
        },
    )
    env.as_user(env.user(201, name="专家甲"))
    await _create_answer(env, qid, "首答内容")
    question = await env.reload_row(Question, id=qid)
    answers = await env.reload_all(Answer, question_id=qid)
    assert question.content_locked == 1
    assert question.answer_count == 1
    assert len(answers) == 1
    env.as_user(env.asker)
    locked_resp = _ok(
        await env.client.put(
            f"{PREFIX}/questions/{qid}",
            json={"title": "改标题", "description": "改正文"},
        )
    )
    assert locked_resp["status_code"] != 200
    locked = await env.reload_row(Question, id=qid)
    assert locked.title == env.t("df05首答锁")
    assert locked.content_locked == 1


async def test_df06_non_invited_answer_does_not_insert(flow_env):
    env = flow_env
    invited = await env.seed_expert(user_id=201, name="专家甲")
    await env.seed_expert(user_id=203, name="专家丙")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df06未受邀",
            "description": "定向",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [invited.id],
            "asker_reveal_on_public": True,
        },
    )
    env.as_user(env.user(203, name="专家丙"))
    before = await env.reload_all(Answer, question_id=qid)
    resp = await env.client.post(
        f"{PREFIX}/answers",
        json={"question_id": qid, "content": "不该写入", "reveal_on_public": True},
    )
    body = _ok(resp)
    assert body["status_code"] != 200
    after = await env.reload_all(Answer, question_id=qid)
    assert len(after) == len(before)


async def test_df07_delete_last_answer_keeps_lock(flow_env):
    env = flow_env

    expert = await env.seed_expert(user_id=201, name="专家甲")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df07锁不解除",
            "description": "正文",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [expert.id],
            "asker_reveal_on_public": True,
        },
    )
    env.as_user(env.user(201, name="专家甲"))
    aid = await _create_answer(env, qid, "将删除的回答")
    resp = await env.client.delete(f"{PREFIX}/answers/{aid}")
    body = _ok(resp)
    assert body["status_code"] == 200
    question = await env.reload_row(Question, id=qid)
    answer = await env.reload_row(Answer, id=aid)
    assert question.content_locked == 1
    assert question.answer_count == 0
    assert answer.status == 3


async def test_df08_public_adopt_writes_eligibility_snapshot(flow_env):
    env = flow_env
    expert_a = await env.seed_expert(user_id=201, name="专家A")
    await env.seed_expert(user_id=202, name="专家B")
    await env.seed_expert(user_id=203, name="专家C")
    await env.seed_expert(user_id=204, name="专家D")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df08公开快照",
            "description": "公开",
            "business_domain": "steel",
            "question_type": "public",
            "invited_expert_ids": [expert_a.id],
        },
    )
    env.as_user(env.user(202, name="专家B"))
    bid = await _create_answer(env, qid, "B的回答")
    await env.client.delete(f"{PREFIX}/answers/{bid}")
    env.as_user(env.user(203, name="专家C"))
    cid = await _create_answer(env, qid, "C的回答")
    env.as_user(env.asker)
    adopt = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": cid}))
    assert adopt["status_code"] == 200
    question = await env.reload_row(Question, id=qid)
    adopts = await env.reload_all(AnswerAdopt, question_id=qid)
    elig = await env.reload_all(AnswerEligibility, question_id=qid)
    elig_users = {int(row.user_id) for row in elig}
    assert question.adopt_count == 1
    assert question.resolved_at is not None
    assert len(adopts) == 1
    assert elig_users == {env.uid(201), env.uid(202), env.uid(203)}
    env.as_user(env.user(204, name="专家D"))
    before = await env.reload_all(Answer, question_id=qid)
    denied = _ok(
        await env.client.post(
            f"{PREFIX}/answers",
            json={"question_id": qid, "content": "圈外不应写入", "reveal_on_public": True},
        )
    )
    assert denied["status_code"] != 200
    after = await env.reload_all(Answer, question_id=qid)
    assert len(after) == len(before)


async def test_df09_fourth_adopt_does_not_write_slot(flow_env):
    env = flow_env
    experts = []
    for i in range(4):
        experts.append(await env.seed_expert(user_id=210 + i, name=f"专家{i}"))
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {"title": "df09四次采纳", "description": "公开", "business_domain": "steel", "question_type": "public"},
    )
    answer_ids = []
    for i, expert in enumerate(experts):
        env.as_user(env.user(expert.user_id, name=expert.expert_name))
        answer_ids.append(await _create_answer(env, qid, f"回答{i}"))
    env.as_user(env.asker)
    for aid in answer_ids[:3]:
        body = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": aid}))
        assert body["status_code"] == 200
    fourth = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": answer_ids[3]}))
    assert fourth["status_code"] != 200
    question = await env.reload_row(Question, id=qid)
    adopts = await env.reload_all(AnswerAdopt, question_id=qid)
    assert question.adopt_count == 3
    assert len(adopts) == 3


async def test_df10_directed_comment_requires_effective_answer(flow_env):
    env = flow_env
    expert_a = await env.seed_expert(user_id=201, name="专家甲")
    expert_b = await env.seed_expert(user_id=202, name="专家乙")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df10评论门禁",
            "description": "定向",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [expert_a.id, expert_b.id],
            "asker_reveal_on_public": True,
        },
    )
    env.as_user(env.user(201, name="专家甲"))
    aid = await _create_answer(env, qid, "甲先答")
    env.as_user(env.user(202, name="专家乙"))
    before = await env.reload_all(Comment, question_id=qid)
    denied = _ok(
        await env.client.post(
            f"{PREFIX}/comments",
            json={"answer_id": aid, "content": "未答不能评", "reveal_on_public": True},
        )
    )
    assert denied["status_code"] != 200
    assert len(await env.reload_all(Comment, question_id=qid)) == len(before)
    await _create_answer(env, qid, "乙后答")
    allowed = _ok(
        await env.client.post(
            f"{PREFIX}/comments",
            json={"answer_id": aid, "content": "已答可评", "reveal_on_public": True},
        )
    )
    assert allowed["status_code"] == 200
    comments = await env.reload_all(Comment, question_id=qid)
    assert len(comments) == 1
    assert comments[0].content == "已答可评"


async def test_df11_disable_expert_blocks_new_answer(flow_env):
    env = flow_env
    expert = await env.seed_expert(user_id=201, name="专家甲")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {"title": "df11停用", "description": "公开", "business_domain": "steel", "question_type": "public"},
    )
    env.as_user(env.portal_admin)
    disabled = _ok(await env.client.post(f"{PREFIX}/experts/{expert.id}/disable"))
    assert disabled["status_code"] == 200
    row = await env.reload_row(Expert, id=expert.id)
    assert row is not None
    assert row.status == 0
    env.as_user(env.user(201, name="专家甲"))
    before = await env.reload_all(Answer, question_id=qid)
    denied = _ok(
        await env.client.post(
            f"{PREFIX}/answers",
            json={"question_id": qid, "content": "停用后不能答"},
        )
    )
    assert denied["status_code"] != 200
    assert len(await env.reload_all(Answer, question_id=qid)) == len(before)


async def test_df12_non_admin_cannot_disable_expert(flow_env):
    env = flow_env
    expert = await env.seed_expert(user_id=201, name="专家甲")
    env.as_user(env.asker)
    denied = _ok(await env.client.post(f"{PREFIX}/experts/{expert.id}/disable"))
    assert denied["status_code"] != 200
    row = await env.reload_row(Expert, id=expert.id)
    assert row.status == 1


async def test_df13_publish_approve_keeps_invites_and_blocks_outsider(flow_env):
    env = flow_env
    invited = await env.seed_expert(user_id=201, name="专家甲")
    await env.seed_expert(user_id=203, name="专家丙")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df13转公开",
            "description": "定向",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [invited.id],
            "asker_reveal_on_public": True,
        },
    )
    env.as_user(env.user(201, name="专家甲"))
    aid = await _create_answer(env, qid, "甲的回答")
    env.as_user(env.asker)
    _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": aid}))
    created = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/publish-requests", json={"duration_days": 3}))
    assert created["status_code"] == 200
    pending_detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    pending_pub = (pending_detail.get("data") or {}).get("latest_publish_request") or {}
    assert pending_pub.get("status") == "pending"
    assert pending_pub.get("viewer_decision") == "approved"
    assert (pending_detail.get("data") or {}).get("active_publish_request", {}).get("status") == "pending"
    assert (pending_detail.get("data") or {}).get("capabilities", {}).get("can_decide_publish") is False
    request_id = int((created.get("data") or {}).get("id") or 0)
    if not request_id:
        req = await env.reload_row(PublishRequest, question_id=qid)
        request_id = int(req.id)
    approvers_pending = await env.reload_all(PublishApprover, request_id=request_id)
    asker_row = next(row for row in approvers_pending if int(row.user_id) == int(env.asker.user_id))
    expert_row = next(row for row in approvers_pending if int(row.user_id) == int(env.uid(201)))
    assert asker_row.decision == "approved"
    assert expert_row.decision == "pending"
    # 再读确认发起人仍是已同意且不能改口
    again = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    assert (again.get("data") or {}).get("latest_publish_request", {}).get("viewer_decision") == "approved"
    assert (again.get("data") or {}).get("capabilities", {}).get("can_decide_publish") is False
    env.as_user(env.user(201, name="专家甲"))
    expert_detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    assert (expert_detail.get("data") or {}).get("latest_publish_request", {}).get("viewer_decision") == "pending"
    assert (expert_detail.get("data") or {}).get("capabilities", {}).get("can_decide_publish") is True
    invites_before = await env.reload_all(QuestionInvite, question_id=qid)
    approved = _ok(await env.client.post(f"{PREFIX}/publish-requests/{request_id}/approve"))
    assert approved["status_code"] == 200
    question = await env.reload_row(Question, id=qid)
    request = await env.reload_row(PublishRequest, id=request_id)
    invites_after = await env.reload_all(QuestionInvite, question_id=qid)
    assert question.question_type == "public"
    assert request.status == "approved"
    approved_detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    latest = (approved_detail.get("data") or {}).get("latest_publish_request") or {}
    assert latest.get("status") == "approved"
    assert (approved_detail.get("data") or {}).get("question_type") == "public"
    assert (approved_detail.get("data") or {}).get("active_publish_request") in (None, {})
    assert len(invites_after) == len(invites_before) == 1
    env.as_user(env.user(203, name="专家丙"))
    before = await env.reload_all(Answer, question_id=qid)
    denied = _ok(
        await env.client.post(
            f"{PREFIX}/answers",
            json={"question_id": qid, "content": "非原受邀不能答"},
        )
    )
    assert denied["status_code"] != 200
    assert len(await env.reload_all(Answer, question_id=qid)) == len(before)
    approvers = await env.reload_all(PublishApprover, request_id=request_id)
    assert approvers


async def _post_as(user, method: str, path: str, json: dict | None = None):
    """独立 ASGI 客户端，避免并发时抢共享 auth。"""
    from test.qa_expert.conftest import _flow_app

    auth = {"user": user}
    app = _flow_app(auth)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await getattr(client, method)(path, json=json)


async def test_df14_concurrent_first_answers_lock_once(flow_env):
    env = flow_env
    await env.seed_expert(user_id=201, name="专家甲")
    await env.seed_expert(user_id=202, name="专家乙")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {"title": "df14并发首答", "description": "公开", "business_domain": "steel", "question_type": "public"},
    )
    r1, r2 = await asyncio.gather(
        _post_as(
            env.user(201, name="专家甲"),
            "post",
            f"{PREFIX}/answers",
            {"question_id": qid, "content": "甲并发答", "reveal_on_public": True},
        ),
        _post_as(
            env.user(202, name="专家乙"),
            "post",
            f"{PREFIX}/answers",
            {"question_id": qid, "content": "乙并发答", "reveal_on_public": True},
        ),
    )
    b1, b2 = _ok(r1), _ok(r2)
    assert b1["status_code"] == 200
    assert b2["status_code"] == 200
    answers = await env.reload_all(Answer, question_id=qid)
    question = await env.reload_row(Question, id=qid)
    assert len(answers) == 2
    assert question.content_locked == 1
    assert question.answer_count == 2


async def test_df15_concurrent_adopt_uses_row_lock(flow_env):
    env = flow_env
    await env.seed_expert(user_id=201, name="专家甲")
    await env.seed_expert(user_id=202, name="专家乙")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {"title": "df15并发采纳", "description": "公开", "business_domain": "steel", "question_type": "public"},
    )
    env.as_user(env.user(201, name="专家甲"))
    a1 = await _create_answer(env, qid, "甲答")
    env.as_user(env.user(202, name="专家乙"))
    a2 = await _create_answer(env, qid, "乙答")
    r1, r2 = await asyncio.gather(
        _post_as(env.asker, "post", f"{PREFIX}/questions/{qid}/adopt", {"answer_id": a1}),
        _post_as(env.asker, "post", f"{PREFIX}/questions/{qid}/adopt", {"answer_id": a2}),
    )
    codes = {_ok(r1)["status_code"], _ok(r2)["status_code"]}
    assert codes == {200}
    question = await env.reload_row(Question, id=qid)
    adopts = await env.reload_all(AnswerAdopt, question_id=qid)
    assert len(adopts) == 2
    assert int(question.adopt_count) == 2
    assert question.content_locked == 1


async def test_df16_list_hides_anonymous_asker_name(flow_env):
    """匿名公开题：库内 created_by 仍是真名；列表接口对路人只给别名。"""
    env = flow_env
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df16匿名公开",
            "description": "匿名正文",
            "business_domain": "营销",
            "question_type": "public",
            "asker_anonymous": True,
        },
    )
    stored = await env.reload_row(Question, id=qid)
    assert int(stored.asker_anonymous) == 1
    assert stored.created_by == "asker"

    env.as_user(env.stranger)
    resp = await env.client.get(
        f"{PREFIX}/questions",
        params={"page": 1, "page_size": 50, "keyword": env.t("df16匿名公开")},
    )
    body = _ok(resp)
    assert body["status_code"] == 200
    items = (body.get("data") or {}).get("questions") or []
    hit = next((item for item in items if int(item.get("id")) == qid), None)
    assert hit is not None
    asker = hit.get("asker") or {}
    assert asker.get("anonymous") is True
    assert asker.get("display_name", "").startswith("匿名同事")
    assert "real_name" not in asker
    assert hit.get("created_by") == asker.get("display_name")
    assert hit.get("created_by") != "asker"
    aliases = await env.reload_all(AnonymousAlias, question_id=qid)
    assert len(aliases) == 1
    stored_again = await env.reload_row(Question, id=qid)
    assert stored_again.created_by == "asker"


async def test_df26_admin_list_shows_anonymous_asker_real_name(flow_env):
    """管理员看问题列表：asker.real_name 为库内真名；路人仍无 real_name。无 DDL。"""
    env = flow_env
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df26列表破匿名",
            "description": "匿名正文",
            "business_domain": "营销",
            "question_type": "public",
            "asker_anonymous": True,
        },
    )
    stored = await env.reload_row(Question, id=qid)
    assert int(stored.asker_anonymous) == 1
    assert stored.created_by == "asker"

    env.as_user(env.stranger)
    stranger_body = _ok(
        await env.client.get(
            f"{PREFIX}/questions",
            params={"page": 1, "page_size": 50, "keyword": env.t("df26列表破匿名")},
        )
    )
    stranger_items = (stranger_body.get("data") or {}).get("questions") or []
    stranger_hit = next((item for item in stranger_items if int(item.get("id")) == qid), None)
    assert stranger_hit is not None
    stranger_asker = stranger_hit.get("asker") or {}
    assert stranger_asker.get("anonymous") is True
    assert "real_name" not in stranger_asker
    assert str(stranger_asker.get("display_name") or "").startswith("匿名同事")

    env.as_user(env.portal_admin)
    admin_body = _ok(
        await env.client.get(
            f"{PREFIX}/questions",
            params={"page": 1, "page_size": 50, "keyword": env.t("df26列表破匿名")},
        )
    )
    admin_items = (admin_body.get("data") or {}).get("questions") or []
    admin_hit = next((item for item in admin_items if int(item.get("id")) == qid), None)
    assert admin_hit is not None
    admin_asker = admin_hit.get("asker") or {}
    assert admin_asker.get("anonymous") is True
    assert admin_asker.get("display_name", "").startswith("匿名同事")
    assert admin_asker.get("real_name") == "asker"
    stored_again = await env.reload_row(Question, id=qid)
    assert stored_again.created_by == "asker"


async def test_df17_directed_anonymous_masks_invited_viewer(flow_env):
    """定向匿名：库内仍是真名；受邀专家详情只见别名，且须预存转公开选项。"""
    env = flow_env
    expert = await env.seed_expert(user_id=201, name="专家甲")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df17定向匿名",
            "description": "定向匿名正文",
            "business_domain": "营销",
            "question_type": "directed",
            "invited_expert_ids": [expert.id],
            "asker_anonymous": True,
            "asker_reveal_on_public": False,
        },
    )
    stored = await env.reload_row(Question, id=qid)
    assert int(stored.asker_anonymous) == 1
    assert int(stored.asker_reveal_on_public) == 0
    assert stored.created_by == "asker"

    env.as_user(env.user(201, name="专家甲"))
    detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    assert detail["status_code"] == 200
    data = detail.get("data") or {}
    asker = data.get("asker") or {}
    assert asker.get("anonymous") is True
    assert str(asker.get("display_name") or "").startswith("匿名同事")
    assert "real_name" not in asker
    assert data.get("created_by") == asker.get("display_name")
    aliases = await env.reload_all(AnonymousAlias, question_id=qid)
    assert len(aliases) == 1

    again = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    assert (again.get("data") or {}).get("created_by") == asker.get("display_name")
    stored_again = await env.reload_row(Question, id=qid)
    assert stored_again.created_by == "asker"
    assert len(await env.reload_all(AnonymousAlias, question_id=qid)) == 1


async def test_df18_list_shows_latest_answer_preview(flow_env):
    """有回答的列表卡片带最新一条；后写的覆盖先写的；采纳后 preview.adopted 与 qa_answer 一致。"""
    env = flow_env
    expert = await env.seed_expert(user_id=201, name="专家甲")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df18列表最新答",
            "description": "公开正文",
            "business_domain": "营销",
            "question_type": "public",
        },
    )

    async def _list_hit():
        env.as_user(env.stranger)
        resp = await env.client.get(
            f"{PREFIX}/questions",
            params={"page": 1, "page_size": 50, "keyword": env.t("df18列表最新答")},
        )
        body = _ok(resp)
        assert body["status_code"] == 200
        items = (body.get("data") or {}).get("questions") or []
        hit = next((item for item in items if int(item.get("id")) == qid), None)
        assert hit is not None
        return hit

    empty = await _list_hit()
    assert not empty.get("latest_answer")

    env.as_user(env.user(201, name="专家甲"))
    first = await _create_answer(env, qid, "第一答")
    second = await _create_answer(env, qid, "第二答")
    preview = (await _list_hit()).get("latest_answer") or {}
    assert preview.get("id") == second
    assert "第二答" in str(preview.get("excerpt") or "")
    assert "第一答" not in str(preview.get("excerpt") or "")
    assert preview.get("adopted") is False
    assert "专家甲" in str(preview.get("expert_name") or "")
    rows = await env.reload_all(Answer, question_id=qid)
    latest = max(rows, key=lambda row: int(row.id))
    assert int(latest.id) == second
    assert int(latest.status) != 3

    env.as_user(env.asker)
    adopt = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": second}))
    assert adopt["status_code"] == 200
    adopted_preview = (await _list_hit()).get("latest_answer") or {}
    assert adopted_preview.get("id") == second
    assert adopted_preview.get("adopted") is True
    stored = await env.reload_row(Answer, id=second)
    assert stored.adopted in (1, True)
    assert first != second


async def test_df19_followup_and_comment_anonymous_inheritance(flow_env):
    """追问继承提问匿名；自评继承回答匿名；评他人独立选择。接口+落库+再读。"""
    env = flow_env
    expert = await env.seed_expert(user_id=201, name="专家甲")
    other = await env.seed_expert(user_id=202, name="专家乙")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df19匿名追问",
            "description": "匿名正文",
            "business_domain": "营销",
            "question_type": "public",
            "asker_anonymous": True,
        },
    )
    stored_q = await env.reload_row(Question, id=qid)
    assert int(stored_q.asker_anonymous) == 1

    follow = _ok(
        await env.client.post(
            f"{PREFIX}/comments",
            json={
                "answer_id": 0,
                "question_id": qid,
                "content": "追问一句",
                "is_follow_up": True,
                "anonymous": False,
            },
        )
    )
    assert follow["status_code"] == 200
    follow_id = int((follow.get("data") or {}).get("id") or 0)
    follow_row = await env.reload_row(Comment, id=follow_id)
    assert int(follow_row.anonymous) == 1
    assert follow_row.user_name == "asker"

    env.as_user(env.stranger)
    listed = _ok(
        await env.client.post(
            f"{PREFIX}/allcomments",
            json={"answer_id": 0, "question_id": qid, "page": 1, "page_size": 20},
        )
    )
    assert listed["status_code"] == 200
    comments = (listed.get("data") or {}).get("comments") or []
    hit = next((item for item in comments if int(item.get("id")) == follow_id), None)
    assert hit is not None
    assert str(hit.get("user_name") or "").startswith("匿名同事")
    assert hit.get("user_name") != "asker"
    assert (hit.get("author") or {}).get("anonymous") is True
    follow_again = await env.reload_row(Comment, id=follow_id)
    assert follow_again.user_name == "asker"

    env.as_user(env.user(201, name=expert.expert_name))
    aid = await _create_answer_anonymous(env, qid, "匿名首答")
    answer_row = await env.reload_row(Answer, id=aid)
    assert int(answer_row.anonymous) == 1
    assert answer_row.expert_name == expert.expert_name

    env.as_user(env.stranger)
    answers_body = _ok(await env.client.get(f"{PREFIX}/answers/{qid}"))
    assert answers_body["status_code"] == 200
    answers = (answers_body.get("data") or {}).get("answers") or []
    ans_hit = next((item for item in answers if int(item.get("id")) == aid), None)
    assert ans_hit is not None
    assert str(ans_hit.get("expert_name") or "").startswith("匿名同事")
    assert ans_hit.get("expert_name") != expert.expert_name
    assert (ans_hit.get("author") or {}).get("anonymous") is True
    assert "real_name" not in (ans_hit.get("author") or {})
    assert not ans_hit.get("expert")
    answer_again = await env.reload_row(Answer, id=aid)
    assert answer_again.expert_name == expert.expert_name

    env.as_user(env.user(201, name=expert.expert_name))
    self_comment = _ok(
        await env.client.post(
            f"{PREFIX}/comments",
            json={"answer_id": aid, "content": "自评补充", "anonymous": False},
        )
    )
    assert self_comment["status_code"] == 200
    self_id = int((self_comment.get("data") or {}).get("id") or 0)
    self_row = await env.reload_row(Comment, id=self_id)
    assert int(self_row.anonymous) == 1

    env.as_user(env.user(202, name=other.expert_name))
    other_comment = _ok(
        await env.client.post(
            f"{PREFIX}/comments",
            json={"answer_id": aid, "content": "他人匿名评", "anonymous": True},
        )
    )
    assert other_comment["status_code"] == 200
    other_id = int((other_comment.get("data") or {}).get("id") or 0)
    other_row = await env.reload_row(Comment, id=other_id)
    assert int(other_row.anonymous) == 1

    env.as_user(env.stranger)
    listed_again = _ok(
        await env.client.post(
            f"{PREFIX}/allcomments",
            json={"answer_id": aid, "question_id": qid, "page": 1, "page_size": 20},
        )
    )
    assert listed_again["status_code"] == 200
    thread = (listed_again.get("data") or {}).get("comments") or []
    self_hit = next((item for item in thread if int(item.get("id")) == self_id), None)
    other_hit = next((item for item in thread if int(item.get("id")) == other_id), None)
    assert self_hit is not None and str(self_hit.get("user_name") or "").startswith("匿名同事")
    assert other_hit is not None and str(other_hit.get("user_name") or "").startswith("匿名同事")
    assert self_hit.get("user_name") != expert.expert_name
    stored_self = await env.reload_row(Comment, id=self_id)
    stored_other = await env.reload_row(Comment, id=other_id)
    assert stored_self.user_name == expert.expert_name
    assert stored_other.user_name == other.expert_name


async def test_df20_directed_anonymous_answer_without_reveal_rejected(flow_env):
    """定向匿名回答未选转公开姓名：18311，qa_answer 无脏行。"""
    env = flow_env
    expert = await env.seed_expert(user_id=201, name="专家甲")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df20定向匿名答",
            "description": "定向正文",
            "business_domain": "营销",
            "question_type": "directed",
            "invited_expert_ids": [expert.id],
            "asker_anonymous": True,
            "asker_reveal_on_public": False,
        },
    )
    before = await env.reload_all(Answer, question_id=qid)
    env.as_user(env.user(201, name=expert.expert_name))
    resp = await env.client.post(
        f"{PREFIX}/answers",
        json={"question_id": qid, "content": "不该写入", "anonymous": True},
    )
    body = _ok(resp)
    assert body["status_code"] == 18311
    after = await env.reload_all(Answer, question_id=qid)
    assert len(after) == len(before)


async def _inbox_rows(env, title: str) -> list[dict]:
    """按站内信正文标题查 inbox_message，核转公开通知是否带 instance_id。"""
    async with AsyncSession(env.engine, expire_on_commit=False) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT id, action_code, receiver, content FROM inbox_message "
                        "WHERE CAST(content AS CHAR) LIKE :p ORDER BY id"
                    ),
                    {"p": f"%{title}%"},
                )
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]


def _receiver_ids(raw) -> set[int]:
    if isinstance(raw, list):
        return {int(uid) for uid in raw}
    if isinstance(raw, str):
        parsed = json.loads(raw)
        return {int(uid) for uid in parsed}
    return set()


async def test_df21_publish_todo_and_late_answerer_joins(flow_env, monkeypatch):
    """转公开先通知相关人，待我处理有 pending task；后回答的受邀专家加入会签并把截止延后 1 天。"""
    from bisheng.approval.domain.models.approval_instance import ApprovalInstance, ApprovalTask
    from bisheng.qa_expert.domain.publish_service import PublishService

    async def live_notify(self, event, question, extra=None):
        await self._send_inbox(event, question, extra or {})

    monkeypatch.setattr(PublishService, "_notify", live_notify)
    env = flow_env
    first = await env.seed_expert(user_id=201, name="专家甲")
    second = await env.seed_expert(user_id=202, name="专家乙")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df21转公开待办",
            "description": "定向",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [first.id, second.id],
            "asker_reveal_on_public": True,
        },
    )
    env.as_user(env.user(201, name="专家甲"))
    aid = await _create_answer(env, qid, "甲先答")
    env.as_user(env.asker)
    _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": aid}))
    created = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/publish-requests", json={"duration_days": 3}))
    assert created["status_code"] == 200
    request = await env.reload_row(PublishRequest, question_id=qid)
    assert request is not None
    assert request.status == "pending"
    approvers = await env.reload_all(PublishApprover, request_id=request.id)
    assert any(int(row.user_id) == env.uid(201) and row.decision == "pending" for row in approvers)
    assert not any(int(row.user_id) == env.uid(202) for row in approvers)
    instance = await env.reload_row(
        ApprovalInstance,
        business_key=f"qa_publish:{request.id}",
        scenario_code="qa_question_publish",
    )
    assert instance is not None
    tasks = await env.reload_all(ApprovalTask, instance_id=instance.id)
    pending_users = {int(row.approver_user_id) for row in tasks if row.status == "pending"}
    assert env.uid(201) in pending_users
    assert env.uid(202) not in pending_users
    title = env.t("df21转公开待办")
    started_msgs = [
        row for row in await _inbox_rows(env, title) if "publish_started" in str(row.get("action_code") or "")
    ]
    assert started_msgs
    started = started_msgs[-1]
    assert env.uid(201) in _receiver_ids(started["receiver"])
    assert env.uid(202) not in _receiver_ids(started["receiver"])
    assert str(instance.id) in str(started["content"])

    env.as_user(env.user(202, name="专家乙"))
    later = await _create_answer(env, qid, "乙后答")
    assert later
    approvers_after = await env.reload_all(PublishApprover, request_id=request.id)
    assert any(int(row.user_id) == env.uid(202) and row.decision == "pending" for row in approvers_after)
    tasks_after = await env.reload_all(ApprovalTask, instance_id=instance.id)
    pending_after = {int(row.approver_user_id) for row in tasks_after if row.status == "pending"}
    assert env.uid(202) in pending_after
    still_pending = await env.reload_row(PublishRequest, id=request.id)
    assert still_pending.status == "pending"
    assert int(still_pending.extension_days or 0) == int(request.extension_days or 0) + 1
    assert still_pending.expire_at - request.expire_at == timedelta(days=1)
    instance_after = await env.reload_row(ApprovalInstance, id=instance.id)
    assert instance_after is not None
    expected_iso = still_pending.expire_at.strftime("%Y-%m-%dT%H:%M:%S") + "+08:00"
    assert (instance_after.payload_snapshot or {}).get("expire_at") == expected_iso
    assert (instance_after.detail_snapshot or {}).get("expire_at") == expected_iso
    detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    latest = (detail.get("data") or {}).get("latest_publish_request") or {}
    assert str(latest.get("expire_at") or "") == expected_iso
    assert int(latest.get("extension_days") or 0) == int(still_pending.extension_days)
    added_msgs = [row for row in await _inbox_rows(env, title) if "approver_added" in str(row.get("action_code") or "")]
    assert added_msgs
    assert env.uid(202) in _receiver_ids(added_msgs[-1]["receiver"])
    still_tasks = await env.reload_all(ApprovalTask, instance_id=instance.id)
    assert {int(row.approver_user_id) for row in still_tasks if row.status == "pending"} == pending_after


async def test_df22_publish_approval_masks_anonymous_names_and_department(flow_env, monkeypatch):
    """定向转公开：匿名提问者/专家在审批实例与详情接口不露真名和部门。"""
    from bisheng.approval.domain.models.approval_instance import ApprovalActionLog, ApprovalInstance, ApprovalTask

    env = flow_env
    invited = await env.seed_expert(user_id=201, name="专家甲")
    asker_real_name = env.asker.user_name
    expert_real_name = "专家甲"
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df22转公开匿名",
            "description": "定向匿名",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [invited.id],
            "asker_anonymous": True,
            "asker_reveal_on_public": False,
        },
    )
    env.as_user(env.user(201, name=expert_real_name))
    aid = await _create_answer_anonymous(env, qid, "匿名有效答", reveal_on_public=False)
    env.as_user(env.asker)
    _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": aid}))
    monkeypatch.setattr(
        "bisheng.database.models.department.UserDepartmentDao.aget_user_primary_department",
        AsyncMock(return_value=SimpleNamespace(department_id=101)),
    )
    created = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/publish-requests", json={"duration_days": 3}))
    assert created["status_code"] == 200

    instance = await env.reload_row(
        ApprovalInstance,
        business_resource_id=str(qid),
        scenario_code="qa_question_publish",
    )
    assert instance is not None
    assert int(instance.applicant_user_id) == int(env.asker.user_id)
    assert str(instance.applicant_user_name).startswith("匿名同事")
    assert instance.applicant_user_name != asker_real_name
    assert instance.applicant_department_id is None

    logs = await env.reload_all(ApprovalActionLog, instance_id=instance.id)
    submitted = next((row for row in logs if row.action == "submitted"), None)
    assert submitted is not None
    assert str(submitted.operator_user_name).startswith("匿名同事")
    assert submitted.operator_user_name != asker_real_name
    assert int(submitted.operator_user_id) == int(env.asker.user_id)

    aliases = await env.reload_all(AnonymousAlias, question_id=qid)
    assert aliases
    alias_labels = {str(row.alias_label) for row in aliases}

    tasks = await env.reload_all(ApprovalTask, instance_id=instance.id)
    expert_task = next((row for row in tasks if int(row.approver_user_id) == env.uid(201)), None)
    assert expert_task is not None

    env.as_user(env.user(201, name=expert_real_name))
    listed = _ok(await env.client.get("/api/v1/approval/my-tasks"))
    assert listed["status_code"] == 200
    task_rows = (listed.get("data") or {}).get("data") or []
    hit = next((item for item in task_rows if int(item.get("task_id") or 0) == int(expert_task.id)), None)
    assert hit is not None
    assert str(hit.get("applicant_user_name") or "").startswith("匿名同事")
    assert hit.get("applicant_user_name") != asker_real_name
    assert hit.get("applicant_department_id") is None
    assert hit.get("applicant_department_name") is None
    assert hit.get("applicant_department_display_name") is None

    detail = _ok(await env.client.get(f"/api/v1/approval/my-tasks/{expert_task.id}"))
    assert detail["status_code"] == 200
    data = detail.get("data") or {}
    assert str(data.get("applicant_user_name") or "").startswith("匿名同事")
    assert data.get("applicant_user_name") != asker_real_name
    assert data.get("applicant_department_id") is None
    assert data.get("applicant_department_name") is None
    assert data.get("applicant_department_display_name") is None
    task_payload = next(
        (item for item in (data.get("tasks") or []) if int(item.get("approver_user_id") or 0) == env.uid(201)),
        None,
    )
    assert task_payload is not None
    assert str(task_payload.get("approver_user_name") or "").startswith("匿名同事")
    assert task_payload.get("approver_user_name") != expert_real_name
    assert int(task_payload.get("approver_user_id")) == env.uid(201)
    submitted_log = next((item for item in (data.get("action_logs") or []) if item.get("action") == "submitted"), None)
    assert submitted_log is not None
    assert str(submitted_log.get("operator_user_name") or "").startswith("匿名同事")
    assert int(submitted_log.get("operator_user_id")) == int(env.asker.user_id)

    again = _ok(await env.client.get(f"/api/v1/approval/my-tasks/{expert_task.id}"))
    again_data = again.get("data") or {}
    assert again_data.get("applicant_user_name") == data.get("applicant_user_name")
    again_task = next(
        (item for item in (again_data.get("tasks") or []) if int(item.get("approver_user_id") or 0) == env.uid(201)),
        None,
    )
    assert again_task is not None
    assert again_task.get("approver_user_name") == task_payload.get("approver_user_name")
    stored = await env.reload_row(ApprovalInstance, id=instance.id)
    assert stored.applicant_user_name == instance.applicant_user_name
    assert stored.applicant_user_name in alias_labels or str(stored.applicant_user_name).startswith("匿名同事")


async def test_df24_named_directed_publish_shows_applicant_department(flow_env, monkeypatch):
    """定向非匿名提问转公开：审批实例与待办接口展示申请人主部门。"""
    from bisheng.approval.domain.models.approval_instance import ApprovalInstance, ApprovalTask

    env = flow_env
    invited = await env.seed_expert(user_id=201, name="专家甲")
    dept_id = 101
    dept_name = "炼铁厂"
    monkeypatch.setattr(
        "bisheng.database.models.department.UserDepartmentDao.aget_user_primary_department",
        AsyncMock(return_value=SimpleNamespace(department_id=dept_id)),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_center_service.DepartmentDao.aget_by_ids",
        AsyncMock(return_value=[SimpleNamespace(id=dept_id, name=dept_name, short_name="炼铁")]),
    )
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df24转公开实名部门",
            "description": "定向非匿名",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [invited.id],
            "asker_anonymous": False,
        },
    )
    env.as_user(env.user(201, name="专家甲"))
    aid = await _create_answer(env, qid, "甲实名答")
    env.as_user(env.asker)
    _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": aid}))
    created = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/publish-requests", json={"duration_days": 3}))
    assert created["status_code"] == 200

    instance = await env.reload_row(
        ApprovalInstance,
        business_resource_id=str(qid),
        scenario_code="qa_question_publish",
    )
    assert instance is not None
    assert int(instance.applicant_user_id) == int(env.asker.user_id)
    assert instance.applicant_user_name == env.asker.user_name
    assert int(instance.applicant_department_id) == dept_id

    tasks = await env.reload_all(ApprovalTask, instance_id=instance.id)
    expert_task = next((row for row in tasks if int(row.approver_user_id) == env.uid(201)), None)
    assert expert_task is not None
    env.as_user(env.user(201, name="专家甲"))
    listed = _ok(await env.client.get("/api/v1/approval/my-tasks"))
    hit = next(
        (
            item
            for item in ((listed.get("data") or {}).get("data") or [])
            if int(item.get("task_id") or 0) == int(expert_task.id)
        ),
        None,
    )
    assert hit is not None
    assert int(hit.get("applicant_department_id") or 0) == dept_id
    shown = str(hit.get("applicant_department_display_name") or hit.get("applicant_department_name") or "")
    assert dept_name
    assert shown
    assert dept_name in shown or shown in dept_name
    detail = _ok(await env.client.get(f"/api/v1/approval/my-tasks/{expert_task.id}"))
    data = detail.get("data") or {}
    assert int(data.get("applicant_department_id") or 0) == dept_id
    again = _ok(await env.client.get(f"/api/v1/approval/my-tasks/{expert_task.id}"))
    assert int((again.get("data") or {}).get("applicant_department_id") or 0) == dept_id
    stored = await env.reload_row(ApprovalInstance, id=instance.id)
    assert int(stored.applicant_department_id) == dept_id


async def test_df13_reject_keeps_viewer_decision_on_latest(flow_env):
    """任一拒绝后申请 ended 为 rejected；详情仍返回本人 viewer_decision，供右上角展示已拒绝。"""
    env = flow_env
    invited = await env.seed_expert(user_id=201, name="专家甲")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df13拒绝决策",
            "description": "定向",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [invited.id],
            "asker_reveal_on_public": True,
        },
    )
    env.as_user(env.user(201, name="专家甲"))
    aid = await _create_answer(env, qid, "甲的回答")
    env.as_user(env.asker)
    _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": aid}))
    created = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/publish-requests", json={"duration_days": 3}))
    request_id = int((created.get("data") or {}).get("id") or 0)
    if not request_id:
        req = await env.reload_row(PublishRequest, question_id=qid)
        request_id = int(req.id)
    env.as_user(env.user(201, name="专家甲"))
    denied = _ok(await env.client.post(f"{PREFIX}/publish-requests/{request_id}/reject"))
    assert denied["status_code"] == 200
    request = await env.reload_row(PublishRequest, id=request_id)
    assert request.status == "rejected"
    expert_row = next(
        row for row in await env.reload_all(PublishApprover, request_id=request_id) if int(row.user_id) == env.uid(201)
    )
    assert expert_row.decision == "rejected"
    detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    latest = (detail.get("data") or {}).get("latest_publish_request") or {}
    assert latest.get("status") == "rejected"
    assert latest.get("viewer_decision") == "rejected"
    assert (detail.get("data") or {}).get("question_type") == "directed"
    assert (detail.get("data") or {}).get("capabilities", {}).get("can_decide_publish") is False
    env.as_user(env.asker)
    asker_detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    asker_latest = (asker_detail.get("data") or {}).get("latest_publish_request") or {}
    assert asker_latest.get("status") == "rejected"
    assert asker_latest.get("viewer_decision") == "approved"
    assert (asker_detail.get("data") or {}).get("capabilities", {}).get("can_start_publish") is True


def _commented_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("action_code") == "qa_answer_commented"]


async def test_df23_comment_notifies_asker_and_answerer(flow_env, monkeypatch):
    """第三人评回答：提问者与回答者都进 inbox_message；自评不再通知自己；拒绝评论不写脏行。"""
    monkeypatch.setattr(CommentService, "_send_comment_notification", _REAL_SEND_COMMENT_NOTIFICATION)
    env = flow_env
    await env.seed_expert(user_id=201, name="专家甲")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df23评论通知提问者",
            "description": "公开题",
            "business_domain": "steel",
            "question_type": "public",
        },
    )
    env.as_user(env.user(201, name="专家甲"))
    aid = await _create_answer(env, qid, "甲先答")
    title = env.t("df23评论通知提问者")
    before_inbox = await _inbox_rows(env, title)
    env.as_user(env.stranger)
    created = _ok(
        await env.client.post(
            f"{PREFIX}/comments",
            json={"answer_id": aid, "content": "第三人来评"},
        )
    )
    assert created["status_code"] == 200
    comments = await env.reload_all(Comment, question_id=qid)
    assert len(comments) == 1
    assert comments[0].content == "第三人来评"
    first_inbox = _commented_rows(await _inbox_rows(env, title))
    assert len(first_inbox) == len(_commented_rows(before_inbox)) + 1
    receivers = _receiver_ids(first_inbox[-1]["receiver"])
    assert env.asker.user_id in receivers
    assert env.uid(201) in receivers
    assert env.stranger.user_id not in receivers

    env.as_user(env.asker)
    self_comment = _ok(
        await env.client.post(
            f"{PREFIX}/comments",
            json={"answer_id": aid, "content": "提问者自评"},
        )
    )
    assert self_comment["status_code"] == 200
    assert len(await env.reload_all(Comment, question_id=qid)) == 2
    after_self = _commented_rows(await _inbox_rows(env, title))
    assert len(after_self) == len(first_inbox) + 1
    self_receivers = _receiver_ids(after_self[-1]["receiver"])
    assert env.uid(201) in self_receivers
    assert env.asker.user_id not in self_receivers

    env.as_user(env.stranger)
    denied = _ok(
        await env.client.post(
            f"{PREFIX}/comments",
            json={"answer_id": 9_999_999_001, "content": "回答不存在"},
        )
    )
    assert denied["status_code"] != 200
    assert len(await env.reload_all(Comment, question_id=qid)) == 2
    assert len(_commented_rows(await _inbox_rows(env, title))) == len(after_self)


async def test_df24_author_delete_answer_rules(flow_env):
    """未采纳可删并级联评论；已采纳拒绝；转公开 pending 拒绝未采纳删答；拒绝后可删。"""
    env = flow_env
    first = await env.seed_expert(user_id=201, name="专家甲")
    second = await env.seed_expert(user_id=202, name="专家乙")
    env.as_user(env.asker)
    public_id = await _create_question(
        env,
        {"title": "df24公开删答", "description": "公开", "business_domain": "steel", "question_type": "public"},
    )
    env.as_user(env.user(201, name="专家甲"))
    public_aid = await _create_answer(env, public_id, "可删答")
    env.as_user(env.stranger)
    commented = _ok(
        await env.client.post(
            f"{PREFIX}/comments",
            json={"answer_id": public_aid, "content": "随答删除"},
        )
    )
    assert commented["status_code"] == 200
    assert len(await env.reload_all(Comment, question_id=public_id)) == 1
    env.as_user(env.user(201, name="专家甲"))
    listed = _ok(await env.client.get(f"{PREFIX}/answers/{public_id}"))
    answers = (listed.get("data") or {}).get("answers") or listed.get("data") or []
    if isinstance(answers, dict):
        answers = answers.get("answers") or []
    hit = next((item for item in answers if int(item.get("id")) == public_aid), None)
    assert hit is not None
    assert hit.get("can_delete") is True
    deleted = _ok(await env.client.delete(f"{PREFIX}/answers/{public_aid}"))
    assert deleted["status_code"] == 200
    stored = await env.reload_row(Answer, id=public_aid)
    assert int(stored.status) == 3
    assert len(await env.reload_all(Comment, question_id=public_id)) == 0
    after = _ok(await env.client.get(f"{PREFIX}/answers/{public_id}"))
    after_answers = (after.get("data") or {}).get("answers") or after.get("data") or []
    if isinstance(after_answers, dict):
        after_answers = after_answers.get("answers") or []
    assert all(int(item.get("id")) != public_aid for item in after_answers)

    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df24转公开锁删",
            "description": "定向",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [first.id, second.id],
            "asker_reveal_on_public": True,
        },
    )
    env.as_user(env.user(201, name="专家甲"))
    adopted_aid = await _create_answer(env, qid, "将被采纳")
    env.as_user(env.user(202, name="专家乙"))
    other_aid = await _create_answer(env, qid, "未采纳")
    env.as_user(env.asker)
    _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": adopted_aid}))
    env.as_user(env.user(201, name="专家甲"))
    adopted_denied = _ok(await env.client.delete(f"{PREFIX}/answers/{adopted_aid}"))
    assert adopted_denied["status_code"] == 18312
    still_adopted = await env.reload_row(Answer, id=adopted_aid)
    assert int(still_adopted.status) != 3
    assert bool(still_adopted.adopted)

    env.as_user(env.asker)
    started = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/publish-requests", json={"duration_days": 3}))
    assert started["status_code"] == 200
    env.as_user(env.user(202, name="专家乙"))
    pending_denied = _ok(await env.client.delete(f"{PREFIX}/answers/{other_aid}"))
    assert pending_denied["status_code"] == 18312
    still_other = await env.reload_row(Answer, id=other_aid)
    assert int(still_other.status) != 3

    request = await env.reload_row(PublishRequest, question_id=qid)
    env.as_user(env.user(201, name="专家甲"))
    rejected = _ok(await env.client.post(f"{PREFIX}/publish-requests/{int(request.id)}/reject"))
    assert rejected["status_code"] == 200
    env.as_user(env.user(202, name="专家乙"))
    after_reject = _ok(await env.client.delete(f"{PREFIX}/answers/{other_aid}"))
    assert after_reject["status_code"] == 200
    gone = await env.reload_row(Answer, id=other_aid)
    assert int(gone.status) == 3

    env.as_user(env.stranger)
    hidden = _ok(await env.client.post(f"{PREFIX}/allcomments", json={"answer_id": adopted_aid, "question_id": qid}))
    assert hidden["status_code"] == 18301


async def test_df25_expired_publish_allows_unadopted_delete(flow_env):
    """转公开 pending 但 expire_at 已过：删答应惰性过期申请，并允许删除未采纳回答。"""
    env = flow_env
    first = await env.seed_expert(user_id=201, name="专家甲")
    second = await env.seed_expert(user_id=202, name="专家乙")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df25过期后可删",
            "description": "定向",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [first.id, second.id],
            "asker_reveal_on_public": True,
        },
    )
    env.as_user(env.user(201, name="专家甲"))
    adopted_aid = await _create_answer(env, qid, "已采纳")
    env.as_user(env.user(202, name="专家乙"))
    other_aid = await _create_answer(env, qid, "未采纳待删")
    env.as_user(env.asker)
    _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": adopted_aid}))
    started = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/publish-requests", json={"duration_days": 1}))
    assert started["status_code"] == 200
    env.as_user(env.user(202, name="专家乙"))
    still_blocked = _ok(await env.client.delete(f"{PREFIX}/answers/{other_aid}"))
    assert still_blocked["status_code"] == 18312
    async with AsyncSession(env.engine, expire_on_commit=False) as session:
        await session.execute(
            text("UPDATE qa_publish_request SET expire_at = :expired WHERE question_id = :qid"),
            {"expired": now_beijing() - timedelta(minutes=1), "qid": qid},
        )
        await session.commit()
    listed = _ok(await env.client.get(f"{PREFIX}/answers/{qid}"))
    answers = (listed.get("data") or {}).get("answers") or listed.get("data") or []
    if isinstance(answers, dict):
        answers = answers.get("answers") or []
    hit = next((item for item in answers if int(item.get("id")) == other_aid), None)
    assert hit is not None
    assert hit.get("can_delete") is True
    deleted = _ok(await env.client.delete(f"{PREFIX}/answers/{other_aid}"))
    assert deleted["status_code"] == 200
    gone = await env.reload_row(Answer, id=other_aid)
    assert int(gone.status) == 3
    request = await env.reload_row(PublishRequest, question_id=qid)
    assert str(request.status) == "expired"
    adopted = await env.reload_row(Answer, id=adopted_aid)
    assert int(adopted.status) != 3
    env.as_user(env.user(202, name="专家乙"))
    listed_again = _ok(await env.client.get(f"{PREFIX}/answers/{qid}"))
    again = (listed_again.get("data") or {}).get("answers") or listed_again.get("data") or []
    if isinstance(again, dict):
        again = again.get("answers") or []
    assert all(int(item.get("id")) != other_aid for item in again)


async def test_df25_admin_sees_anonymous_answer_expert_meta(flow_env):
    """管理员看匿名回答：接口给真名+部门+计数；路人仍无档案。qa_expert 只读后写计数，无 DDL。"""
    env = flow_env
    expert = await env.seed_expert(user_id=201, name="专家甲")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df25匿名答档案",
            "description": "公开",
            "business_domain": "steel",
            "question_type": "public",
        },
    )
    env.as_user(env.user(201, name=expert.expert_name))
    aid = await _create_answer_anonymous(env, qid, "匿名首答")
    async with AsyncSession(env.engine, expire_on_commit=False) as session:
        await session.execute(
            text("UPDATE qa_expert SET answer_count = :ac, adoption_count = :ad, depart_ment = :d WHERE id = :id"),
            {"ac": 109, "ad": 53, "d": "测试2-2设备", "id": int(expert.id)},
        )
        await session.commit()
    stored = await env.reload_row(Expert, id=int(expert.id))
    assert int(stored.answer_count) == 109
    assert int(stored.adoption_count) == 53
    assert stored.depart_ment == "测试2-2设备"

    env.as_user(env.stranger)
    stranger_body = _ok(await env.client.get(f"{PREFIX}/answers/{qid}"))
    assert stranger_body["status_code"] == 200
    stranger_answers = (stranger_body.get("data") or {}).get("answers") or []
    stranger_hit = next((item for item in stranger_answers if int(item.get("id")) == aid), None)
    assert stranger_hit is not None
    stranger_author = stranger_hit.get("author") or {}
    assert stranger_author.get("anonymous") is True
    assert "real_name" not in stranger_author
    assert "department" not in stranger_author
    assert not stranger_hit.get("expert")
    stored_again = await env.reload_row(Expert, id=int(expert.id))
    assert int(stored_again.answer_count) == 109

    env.as_user(env.portal_admin)
    admin_body = _ok(await env.client.get(f"{PREFIX}/answers/{qid}"))
    assert admin_body["status_code"] == 200
    admin_answers = (admin_body.get("data") or {}).get("answers") or []
    admin_hit = next((item for item in admin_answers if int(item.get("id")) == aid), None)
    assert admin_hit is not None
    admin_author = admin_hit.get("author") or {}
    assert admin_author.get("anonymous") is True
    assert admin_author.get("real_name") == expert.expert_name
    assert admin_author.get("department") == "测试2-2设备"
    admin_expert = admin_hit.get("expert") or {}
    assert int(admin_expert.get("answer_count") or 0) == 109
    assert int(admin_expert.get("adoption_count") or 0) == 53
    assert admin_expert.get("depart_ment") == "测试2-2设备"
    answer_row = await env.reload_row(Answer, id=aid)
    assert int(answer_row.anonymous) == 1
    assert answer_row.expert_name == expert.expert_name


async def test_df_question_too_many_images_rejected_no_dirty_row(flow_env, monkeypatch):
    """提问超过 3 张图返回 18313, qa_question 无脏行."""
    env = flow_env
    stub_storage = SimpleNamespace(
        tmp_bucket="tmp-dir",
        bucket="bisheng",
        minio_config=SimpleNamespace(endpoint="minio:9000", sharepoint="minio:9000"),
    )
    monkeypatch.setattr(
        "bisheng.qa_expert.domain.services.get_minio_storage",
        AsyncMock(return_value=stub_storage),
    )
    title = env.t("df图片超限")
    before = await env.reload_row(Question, title=title)
    assert before is None
    env.as_user(env.asker)
    payload = {
        "title": title,
        "description": "四张图应被拒绝",
        "business_domain": "营销",
        "question_type": "public",
        "image_url": ";".join(f"tmp-dir/{index}.png" for index in range(4)),
    }
    resp = await env.client.post(f"{PREFIX}/questions", json=payload)
    body = _ok(resp)
    assert body["status_code"] == 18313
    assert "提问最多上传 3 张图片" in str(body.get("status_message") or "")
    after = await env.reload_row(Question, title=title)
    assert after is None
    again = await env.client.post(f"{PREFIX}/questions", json=payload)
    again_body = _ok(again)
    assert again_body["status_code"] == 18313
    assert await env.reload_row(Question, title=title) is None


async def test_df_publish_approved_inbox_includes_asker(flow_env, monkeypatch):
    """定向转公开通过后，提问者与回答专家都收到 qa_publish_approved；再读仍在。"""
    from bisheng.qa_expert.domain.publish_service import PublishService

    async def live_notify(self, event, question, extra=None):
        await self._send_inbox(event, question, extra or {})

    monkeypatch.setattr(PublishService, "_notify", live_notify)
    env = flow_env
    invited = await env.seed_expert(user_id=201, name="专家甲")
    env.as_user(env.asker)
    qid = await _create_question(
        env,
        {
            "title": "df转公开提问者通知",
            "description": "定向",
            "business_domain": "steel",
            "question_type": "directed",
            "invited_expert_ids": [invited.id],
            "asker_reveal_on_public": True,
        },
    )
    env.as_user(env.user(201, name="专家甲"))
    aid = await _create_answer(env, qid, "甲的回答")
    env.as_user(env.asker)
    _ok(await env.client.post(f"{PREFIX}/questions/{qid}/adopt", json={"answer_id": aid}))
    created = _ok(await env.client.post(f"{PREFIX}/questions/{qid}/publish-requests", json={"duration_days": 3}))
    assert created["status_code"] == 200
    request = await env.reload_row(PublishRequest, question_id=qid)
    assert request is not None
    title = env.t("df转公开提问者通知")
    before_approved = [
        row for row in await _inbox_rows(env, title) if "publish_approved" in str(row.get("action_code") or "")
    ]
    assert before_approved == []
    env.as_user(env.user(201, name="专家甲"))
    approved = _ok(await env.client.post(f"{PREFIX}/publish-requests/{request.id}/approve"))
    assert approved["status_code"] == 200
    question = await env.reload_row(Question, id=qid)
    assert question.question_type == "public"
    approved_msgs = [
        row for row in await _inbox_rows(env, title) if "publish_approved" in str(row.get("action_code") or "")
    ]
    assert approved_msgs
    receivers = _receiver_ids(approved_msgs[-1]["receiver"])
    assert int(env.asker.user_id) in receivers
    assert env.uid(201) in receivers
    again = await env.reload_row(Question, id=qid)
    assert again.question_type == "public"
    again_msgs = [
        row for row in await _inbox_rows(env, title) if "publish_approved" in str(row.get("action_code") or "")
    ]
    assert int(env.asker.user_id) in _receiver_ids(again_msgs[-1]["receiver"])
    assert env.uid(201) in _receiver_ids(again_msgs[-1]["receiver"])


async def test_df_question_created_at_is_beijing_wall_clock(flow_env):
    """新写入 qa_question.created_at 为东八墙钟；接口带 +08:00，与落库一致。"""
    env = flow_env
    env.as_user(env.asker)
    before = now_beijing()
    qid = await _create_question(
        env,
        {
            "title": "df时区东八",
            "description": "校验墙钟",
            "business_domain": "steel",
            "question_type": "public",
        },
    )
    after = now_beijing()
    row = await env.reload_row(Question, id=qid)
    assert row is not None
    assert row.created_at.tzinfo is None
    assert before - timedelta(seconds=5) <= row.created_at <= after + timedelta(seconds=5)
    detail = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    created_at = (detail.get("data") or {}).get("created_at")
    assert isinstance(created_at, str)
    assert created_at.endswith("+08:00")
    wall = row.created_at.strftime("%Y-%m-%dT%H:%M")
    assert created_at.startswith(wall)
    again = _ok(await env.client.get(f"{PREFIX}/questions/{qid}"))
    assert (again.get("data") or {}).get("created_at") == created_at
    listed = _ok(await env.client.get(f"{PREFIX}/questions", params={"page": 1, "page_size": 20}))
    questions = (listed.get("data") or {}).get("questions") or []
    hit = next((item for item in questions if int(item.get("id")) == qid), None)
    assert hit is not None
    assert str(hit.get("created_at") or "").endswith("+08:00")
