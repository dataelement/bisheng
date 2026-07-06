"""Tests for linsight task-title generation under reasoning models.

qwen3.5 & co. inline ``<think>...</think>`` into the title-model response (or
spend the whole budget on reasoning, leaving an empty answer). The title must
be cleaned + clamped, and empty results must fall back to the user's question
rather than getting stuck on the "New Chat" placeholder.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl


class TestNormalizeTitle:
    def test_strips_think_block(self):
        assert LinsightWorkbenchImpl._normalize_title("<think>想一想</think>季度财报分析", "问题") == "季度财报分析"

    def test_empty_content_falls_back_to_question(self):
        assert LinsightWorkbenchImpl._normalize_title("", "调研两个知识库") == "调研两个知识库"

    def test_pure_think_falls_back_to_question(self):
        assert LinsightWorkbenchImpl._normalize_title("<think>只有推理</think>", "问题原文") == "问题原文"

    def test_none_content_falls_back(self):
        assert LinsightWorkbenchImpl._normalize_title(None, "问题") == "问题"

    def test_first_line_only(self):
        assert LinsightWorkbenchImpl._normalize_title("标题第一行\n多余第二行", "q") == "标题第一行"

    def test_long_title_clamped(self):
        out = LinsightWorkbenchImpl._normalize_title("标" * 100, "q")
        assert len(out) == LinsightWorkbenchImpl._TITLE_MAX_CHARS


class TestFallbackTitle:
    def test_question_slice(self):
        assert LinsightWorkbenchImpl._fallback_title("这是一个问题") == "这是一个问题"

    def test_first_line(self):
        assert LinsightWorkbenchImpl._fallback_title("首行\n次行") == "首行"

    def test_long_question_clamped(self):
        out = LinsightWorkbenchImpl._fallback_title("问" * 100)
        assert len(out) == LinsightWorkbenchImpl._TITLE_MAX_CHARS

    def test_empty_question_returns_placeholder(self):
        assert LinsightWorkbenchImpl._fallback_title("") == "New Chat"
        assert LinsightWorkbenchImpl._fallback_title("   ") == "New Chat"


class TestTaskTitleGenerate:
    async def test_happy_path_strips_think_and_persists(self):
        login_user = SimpleNamespace(user_id=1)
        fake_llm = SimpleNamespace(
            ainvoke=AsyncMock(return_value=AIMessage(content="<think>想一想</think>季度财报分析"))
        )
        with (
            patch.object(LinsightWorkbenchImpl, "_get_llm", new=AsyncMock(return_value=(fake_llm, None))),
            patch.object(
                LinsightWorkbenchImpl,
                "_generate_title_prompt",
                new=AsyncMock(return_value=[("system", "s"), ("user", "u")]),
            ),
            patch.object(LinsightWorkbenchImpl, "_update_session_title", new=AsyncMock()) as upd,
        ):
            result = await LinsightWorkbenchImpl.task_title_generate(
                question="分析季度财报", chat_id="c1", login_user=login_user
            )
        assert result["task_title"] == "季度财报分析"
        assert result["error_message"] is None
        upd.assert_awaited_once_with("c1", "季度财报分析")

    async def test_empty_content_uses_question_fallback(self):
        login_user = SimpleNamespace(user_id=1)
        fake_llm = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="<think>只思考没正文</think>")))
        with (
            patch.object(LinsightWorkbenchImpl, "_get_llm", new=AsyncMock(return_value=(fake_llm, None))),
            patch.object(LinsightWorkbenchImpl, "_generate_title_prompt", new=AsyncMock(return_value=[])),
            patch.object(LinsightWorkbenchImpl, "_update_session_title", new=AsyncMock()) as upd,
        ):
            result = await LinsightWorkbenchImpl.task_title_generate(
                question="调研两个知识库", chat_id="c1", login_user=login_user
            )
        assert result["task_title"] == "调研两个知识库"
        upd.assert_awaited_once_with("c1", "调研两个知识库")

    async def test_llm_failure_writes_question_fallback(self):
        login_user = SimpleNamespace(user_id=1)
        with (
            patch.object(LinsightWorkbenchImpl, "_get_llm", new=AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(LinsightWorkbenchImpl, "_update_session_title", new=AsyncMock()) as upd,
        ):
            result = await LinsightWorkbenchImpl.task_title_generate(
                question="用户问题原文", chat_id="c1", login_user=login_user
            )
        assert result["task_title"] == "用户问题原文"
        assert result["error_message"] == "boom"
        upd.assert_awaited_once_with("c1", "用户问题原文")
