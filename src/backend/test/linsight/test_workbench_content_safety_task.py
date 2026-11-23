"""F063 input intercept on ``/linsight/workbench/submit``: a blocked question creates no session version.

The same intercept of the unified send entry is covered by ``test/workstation/test_unified_run_api.py``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bisheng.linsight.api.endpoints import linsight as linsight_ep
from bisheng.linsight.domain.schemas.linsight_schema import LinsightQuestionSubmitSchema
from bisheng.sensitive_word.domain.schemas import SensitiveWordCheckResult, SensitiveWordHit


AUTO_REPLY = "当前对话内容违反相关规范，请修改后重新输入"
HIT = SensitiveWordCheckResult(
    enabled=True,
    hits=[SensitiveWordHit(word="禁", count=1)],
    auto_reply=AUTO_REPLY,
)


async def _drain(response) -> list:
    return [chunk async for chunk in response.body_iterator]


async def test_legacy_submit_hit_does_not_create_session(monkeypatch):
    monkeypatch.setattr(
        linsight_ep.SensitiveWordPolicyService,
        "evaluate_workbench_user_text",
        staticmethod(lambda *_a, **_k: HIT),
    )
    submit = AsyncMock()
    monkeypatch.setattr(linsight_ep.LinsightWorkbenchImpl, "submit_user_question", submit)
    login = MagicMock()
    login.user_id = 1
    login.tenant_id = 1
    resp = await linsight_ep.submit_linsight_workbench(
        LinsightQuestionSubmitSchema(question="禁词"),
        login,
    )
    chunks = await _drain(resp)
    blob = "".join(
        c if isinstance(c, str) else json.dumps(c, ensure_ascii=False) if isinstance(c, dict) else str(c)
        for c in chunks
    )
    assert "linsight_workbench_submit" not in blob
    assert "content_safety_blocked" in blob
    assert AUTO_REPLY in blob
    submit.assert_not_awaited()


async def test_legacy_submit_hit_marks_existing_session(monkeypatch):
    monkeypatch.setattr(
        linsight_ep.SensitiveWordPolicyService,
        "evaluate_workbench_user_text",
        staticmethod(lambda *_a, **_k: HIT),
    )
    marked = MagicMock()
    monkeypatch.setattr(linsight_ep.MessageSessionDao, "update_sensitive_status", marked)
    login = MagicMock()
    login.user_id = 1
    login.tenant_id = 1
    resp = await linsight_ep.submit_linsight_workbench(
        MagicMock(),
        LinsightQuestionSubmitSchema(question="禁词", session_id="chat-9"),
        login,
    )
    await _drain(resp)
    marked.assert_called_once()
    assert marked.call_args.args[0] == "chat-9"


async def test_legacy_submit_miss_still_submits(monkeypatch):
    monkeypatch.setattr(
        linsight_ep.SensitiveWordPolicyService,
        "evaluate_workbench_user_text",
        staticmethod(lambda *_a, **_k: None),
    )
    session = MagicMock()
    session.model_dump.return_value = {"chat_id": "c1"}
    version = MagicMock()
    version.public_dump.return_value = {"id": "sv"}
    version.title = None
    submit = AsyncMock(return_value=(session, version))
    monkeypatch.setattr(linsight_ep.LinsightWorkbenchImpl, "submit_user_question", submit)
    monkeypatch.setattr(
        linsight_ep,
        "settings",
        SimpleNamespace(aget_all_config=AsyncMock(return_value={})),
    )
    monkeypatch.setattr(
        linsight_ep.LinsightWorkbenchImpl,
        "task_title_generate",
        AsyncMock(return_value={"task_title": "t"}),
    )
    monkeypatch.setattr(linsight_ep.LinsightSessionVersionDao, "insert_one", AsyncMock())
    login = MagicMock()
    login.user_id = 1
    login.tenant_id = 1
    resp = await linsight_ep.submit_linsight_workbench(
        LinsightQuestionSubmitSchema(question="写周报"),
        login,
    )
    await _drain(resp)
    submit.assert_awaited_once()
