"""P1: experience consolidation from deep-research rounds (AC-50, AC-54, AC-55)."""

import json

from sqlmodel import select

from bisheng.memory.domain.models.memory_item import MemoryItem
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.consolidation_content import ConsolidationContent
from bisheng.memory.domain.services.consolidation_linsight import LinsightRoundConsolidation
from bisheng.memory.domain.services.consolidation_prompt import LINSIGHT_INSTRUCTIONS
from bisheng.memory.domain.services.resident import ResidentService
from test.memory.conftest import TENANT_A, USER_1
from test.memory.test_consolidator_linsight import _add_round, _seed_chat


async def _run_round(memory_db, service, llm, answer):
    _seed_chat(memory_db)
    _add_round(memory_db, 501)

    async def reader(chat_id, message_id):
        return {"finished": True, "question": "调研国内向量数据库选型，按我的固定格式出报告", "answer": "报告正文……"}

    llm.answers = [answer]
    step = LinsightRoundConsolidation(service=service, content=ConsolidationContent(llm), reader=reader)
    await step(TENANT_A, USER_1)


async def test_ac50_round_uses_experience_prompt_and_yields_experience_item(memory_db, service, llm, make_ctx, kv):
    answer = json.dumps(
        {"candidates": [{"content": "做选型调研时先列评估维度再填数据，用户认可这样效果好", "type": "experience", "pinned": True}]},
        ensure_ascii=False,
    )
    await _run_round(memory_db, service, llm, answer)
    assert LINSIGHT_INSTRUCTIONS.splitlines()[0] in llm.prompts[0]
    async with _db.async_session() as s:
        items = list((await s.exec(select(MemoryItem))).all())
    assert [(i.type, i.pinned, i.source_scene, i.origin) for i in items] == [("experience", False, "linsight", "auto")]

    resident = ResidentService(kv=kv, metrics=m.MemoryMetrics(kv))
    ctx = make_ctx()
    assert "先列评估维度" in (await resident.experience(ctx)).text  # AC-55: next deep-research task
    assert "先列评估维度" not in (await resident.resident(ctx, "chat")).text  # AC-54


async def test_daily_sessions_keep_the_chat_prompt(memory_db, service, llm, make_ctx):
    await ConsolidationContent(llm).from_messages(make_ctx(scene="daily"), [("用户", "我在华东区")])
    assert LINSIGHT_INSTRUCTIONS.splitlines()[0] not in llm.prompts[0]
