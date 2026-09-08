"""Knowledge-space image-view wiring (F061 T009).

Covers AC: AC-02, AC-03, AC-11, AC-13, AC-14
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from bisheng.api.v1.schemas import KnowledgeSpaceConfig
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService

_YAML = Path(__file__).resolve().parents[2] / "bisheng" / "core" / "prompts" / "yaml" / "knowledge_space.yaml"
_IMG = "![chart](/bisheng/knowledge/images/1/2/chart.png)"


def _service() -> KnowledgeSpaceChatService:
    user = MagicMock()
    user.user_id = 7
    user.tenant_id = 1
    return KnowledgeSpaceChatService(request=MagicMock(), login_user=user)


def test_default_yaml_is_not_rewritten_with_view_image_rules():
    text = _YAML.read_text(encoding="utf-8")
    assert "view_image" not in text
    assert "⟦img#" not in text


def test_apply_image_anchors_when_visual_and_markdown():
    text, registry = KnowledgeSpaceChatService._apply_image_anchors(f"body {_IMG}", visual=True)
    assert f"{_IMG}⟦img#1⟧" in text
    assert registry.get("img#1") == {"url": "/bisheng/knowledge/images/1/2/chart.png"}


def test_apply_image_anchors_skipped_when_not_visual():
    raw = f"body {_IMG}"
    text, registry = KnowledgeSpaceChatService._apply_image_anchors(raw, visual=False)
    assert text == raw
    assert "⟦img#" not in text
    assert len(registry) == 0


def test_apply_image_anchors_noop_without_markdown_image():
    raw = "plain chunk <img src='/x.png'>"
    text, registry = KnowledgeSpaceChatService._apply_image_anchors(raw, visual=True)
    assert text == raw
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_resolve_workbench_visual_reads_wsmodel(monkeypatch):
    service = _service()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.LLMService.get_workbench_llm",
        AsyncMock(
            return_value=SimpleNamespace(
                models=[SimpleNamespace(id="11", visual=True), SimpleNamespace(id="12", visual=False)]
            )
        ),
    )
    assert await service._resolve_workbench_visual(11) is True
    assert await service._resolve_workbench_visual(12) is False
    assert await service._resolve_workbench_visual(99) is False


@pytest.mark.asyncio
async def test_render_uses_vision_loop_when_visual_and_images(monkeypatch):
    service = _service()
    llm = MagicMock()
    space_conf = KnowledgeSpaceConfig(
        system_prompt="sys {cur_date}",
        user_prompt="{retrieved_file_content}\n{question}",
    )
    monkeypatch.setattr(service, "get_space_llm_config", AsyncMock(return_value=(llm, space_conf)))
    monkeypatch.setattr(
        service,
        "_prepare_rag_citation_context",
        AsyncMock(return_value=(f"chunk {_IMG}", [])),
    )
    monkeypatch.setattr(service, "_resolve_workbench_visual", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "get_history", AsyncMock(return_value=[]))

    loop_calls: list[tuple] = []

    async def fake_loop(model, messages, registry, *, visual):
        loop_calls.append((visual, len(registry), "".join(str(m.content) for m in messages)))
        yield AIMessage(content="answer with ![](/bisheng/knowledge/images/1/2/chart.png)")

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.run_react_vision_stream",
        fake_loop,
    )

    async def _insert(rows):
        for index, row in enumerate(rows, start=1):
            row.id = index

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.ChatMessageDao.ainsert_batch",
        _insert,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.save_message_citations",
        AsyncMock(),
    )

    session = SimpleNamespace(chat_id="c1", flow_id="f1", name="named")
    events = [event async for event in service._render_rag_response(session, [], "what trend", 11)]

    assert loop_calls
    visual, registry_len, joined = loop_calls[0]
    assert visual is True
    assert registry_len == 1
    assert "⟦img#1⟧" in joined
    assert any(event.type == "stream" for event in events)


@pytest.mark.asyncio
async def test_render_does_not_annotate_when_visual_false(monkeypatch):
    service = _service()
    llm = MagicMock()
    space_conf = KnowledgeSpaceConfig(
        system_prompt="sys {cur_date}", user_prompt="{retrieved_file_content}\n{question}"
    )
    monkeypatch.setattr(service, "get_space_llm_config", AsyncMock(return_value=(llm, space_conf)))
    monkeypatch.setattr(service, "_prepare_rag_citation_context", AsyncMock(return_value=(f"chunk {_IMG}", [])))
    monkeypatch.setattr(service, "_resolve_workbench_visual", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "get_history", AsyncMock(return_value=[]))

    loop_calls: list[tuple] = []

    async def fake_loop(model, messages, registry, *, visual):
        loop_calls.append((visual, len(registry), "".join(str(m.content) for m in messages)))
        yield AIMessage(content="ok")

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.run_react_vision_stream",
        fake_loop,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.ChatMessageDao.ainsert_batch",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.save_message_citations",
        AsyncMock(),
    )

    session = SimpleNamespace(chat_id="c1", flow_id="f1", name="named")
    async for _ in service._render_rag_response(session, [], "q", 11):
        pass

    visual, registry_len, joined = loop_calls[0]
    assert visual is False
    assert registry_len == 0
    assert "⟦img#" not in joined
