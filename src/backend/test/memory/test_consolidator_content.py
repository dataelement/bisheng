"""Consolidation content: which messages, which candidates (AC-04, AC-39, AC-42)."""

import json
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from bisheng.database.models.assistant import Assistant
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.session import MessageSession
from bisheng.memory.domain.config import MemoryRuntimeConfig
from bisheng.memory.domain.models.memory_item import STATUS_SUPERSEDED, MemoryItem
from bisheng.memory.domain.models.memory_session_cursor import MemorySessionCursor
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.consolidation_content import ConsolidationContent
from bisheng.memory.domain.services.consolidator import Consolidator
from bisheng.user.domain.models.user import User
from test.memory.conftest import TENANT_A, USER_1, make_message


def _start_node(enabled):
    return {
        "nodes": [
            {"data": {"type": "start", "group_params": [{"params": [{"key": "memory_enabled", "value": enabled}]}]}}
        ]
    }


def _seed(memory_db, chat_id, flow_type=15, flow_id="", messages=(), watermark=0):
    with memory_db.session() as s:
        if s.get(User, USER_1) is None:
            s.add(User(user_id=USER_1, user_name="u", password="x"))
        s.add(MessageSession(chat_id=chat_id, flow_id=flow_id, flow_type=flow_type, user_id=USER_1, name="c"))
        ids = []
        for category, text, is_bot in messages:
            msg = make_message(chat_id, USER_1, text, category=category, is_bot=is_bot, flow_id=flow_id)
            s.add(msg)
            s.flush()
            ids.append(msg.id)
        s.add(
            MemorySessionCursor(
                chat_id=chat_id,
                tenant_id=TENANT_A,
                user_id=USER_1,
                state="pending",
                last_activity_at=datetime.now() - timedelta(hours=1),
                last_message_id=ids[-1],
                watermark_message_id=ids[watermark - 1] if watermark else 0,
            )
        )
        s.commit()
    return ids


@pytest.fixture
def run(service, kv, llm):
    async def _run():
        content = ConsolidationContent(llm=llm)
        await Consolidator(service=service, kv=kv, metrics=m.MemoryMetrics(kv), content_fn=content).consolidate_user(
            TENANT_A, USER_1
        )

    return _run


def _answer(*ops):
    return json.dumps({"candidates": list(ops)}, ensure_ascii=False)


async def _items():
    async with _db.async_session() as s:
        return list((await s.exec(select(MemoryItem))).all())


async def test_ac39_only_new_non_task_messages_are_read(memory_db, run, llm):
    _seed(
        memory_db,
        "c1",
        messages=[
            ("question", "旧问题", False),
            ("question", "我在华东区做售前", False),
            ("task", '{"task": "深度研究结果"}', True),
            ("agent_answer", json.dumps({"msg": "好的，记住了你的岗位"}), True),
        ],
        watermark=1,
    )
    llm.answers = [_answer({"content": "用户在华东区做售前", "type": "fact"})]
    await run()
    prompt = llm.prompts[0]
    assert "我在华东区做售前" in prompt and "好的，记住了你的岗位" in prompt
    assert "旧问题" not in prompt and "深度研究结果" not in prompt
    item = (await _items())[0]
    assert (item.origin, item.source_scene, item.source_chat_id) == ("auto", "daily", "c1")


async def test_invalid_candidates_dropped_others_kept(memory_db, run, llm):
    _seed(memory_db, "c1", messages=[("question", "一些对话", False)])
    llm.answers = [
        _answer(
            {"content": "长" * 201, "type": "fact"},
            {"content": "用户的密码是 abc12345", "type": "fact"},
            {"content": "用户明天出差", "type": "fact"},
            {"content": "用户偏好用表格对比方案", "type": "preference"},
        )
    ]
    await run()
    assert [i.content for i in await _items()] == ["用户偏好用表格对比方案"]


async def test_duplicate_skipped_and_contradiction_supersedes(memory_db, run, llm, service, make_ctx):
    dup = await service.write(make_ctx(), "remember", content="用户喜欢喝绿茶", type="preference")
    old = await service.write(make_ctx(), "remember", content="用户的上级是张总", type="fact")
    _seed(memory_db, "c1", messages=[("question", "我换上级了，现在是李总", False)])
    llm.answers = [
        _answer(
            {"content": "用户喜欢喝绿茶", "type": "preference", "duplicate_of": dup.item_id},
            {"content": "用户的上级是李总", "type": "fact", "contradicts": old.item_id},
        )
    ]
    await run()
    items = {i.content: i for i in await _items()}
    assert list(items).count("用户喜欢喝绿茶") == 1
    assert items["用户的上级是张总"].status == STATUS_SUPERSEDED
    assert items["用户的上级是张总"].superseded_by == items["用户的上级是李总"].id
    assert "用户喜欢喝绿茶" in llm.prompts[0] and dup.item_id in llm.prompts[0]  # existing items are shown


async def test_ac42_assistant_session_uses_app_switch_and_source(memory_db, run, llm):
    with memory_db.session() as s:
        s.add(Assistant(id="asst-1", name="差旅助手", tenant_id=TENANT_A, user_id=1, memory_enabled=True))
        s.commit()
    _seed(
        memory_db,
        "a1",
        flow_type=5,
        flow_id="asst-1",
        messages=[("question", "我常住北京", False), ("answer", "了解", True), ("tool", "工具原文", True)],
    )
    llm.answers = [_answer({"content": "用户常住北京", "type": "fact"})]
    await run()
    assert "工具原文" not in llm.prompts[0]
    item = (await _items())[0]
    assert (item.source_scene, item.source_app_id, item.source_app_name) == ("assistant", "asst-1", "差旅助手")


async def test_assistant_switch_off_means_no_consolidation(memory_db, run, llm):
    with memory_db.session() as s:
        s.add(Assistant(id="asst-2", name="x", tenant_id=TENANT_A, user_id=1, memory_enabled=False))
        s.commit()
    _seed(memory_db, "a2", flow_type=5, flow_id="asst-2", messages=[("question", "hi", False)])
    await run()
    assert llm.prompts == []


async def test_ac49_workflow_only_inputs_and_outputs(memory_db, run, llm):
    with memory_db.session() as s:
        s.add(Flow(id="wf1", name="报销流程", tenant_id=TENANT_A, user_id=1, status=2, flow_type=10))
        s.add(FlowVersion(flow_id="wf1", name="v1", is_current=1, data=_start_node(True), user_id=1))
        s.commit()
    _seed(
        memory_db,
        "w1",
        flow_type=10,
        flow_id="wf1",
        messages=[
            ("question", "我的成本中心是 C-100", False),
            ("node_run", "节点内部日志", True),
            ("output_msg", "已为成本中心 C-100 提交", True),
        ],
    )
    llm.answers = [_answer({"content": "用户的成本中心是 C-100", "type": "fact"})]
    await run()
    assert "节点内部日志" not in llm.prompts[0] and "已为成本中心 C-100 提交" in llm.prompts[0]
    assert (await _items())[0].source_app_name == "报销流程"


async def test_resident_adjustment_respects_limit(memory_db, run, llm, service, make_ctx, monkeypatch):
    cfg = MemoryRuntimeConfig(resident_max_items=2)

    async def _load():
        return cfg

    monkeypatch.setattr("bisheng.memory.domain.config.aget_memory_config", _load)
    monkeypatch.setattr("bisheng.memory.domain.services.consolidator.aget_memory_config", _load)
    a = await service.write(make_ctx(), "remember", content="用户住在青岛", type="fact")
    _seed(memory_db, "c1", messages=[("question", "对话", False)])
    llm.answers = [
        _answer(
            {"content": "用户在做海洋数据项目", "type": "fact", "pinned": True},
            {"content": "用户喜欢简短回答", "type": "preference", "pinned": True},
        )
    ]
    await run()
    pinned = [i for i in await _items() if i.pinned and i.status == "active"]
    assert len(pinned) == 2 and a.item_id in [i.id for i in pinned]


async def test_no_new_messages_no_model_call(memory_db, run, llm):
    _seed(memory_db, "c1", messages=[("question", "已整理过", False)], watermark=1)
    await run()
    assert llm.prompts == []
