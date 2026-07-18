"""POC P4 — 中文模型 call_reason 填写遵从率 + Skill progressive disclosure 命中率 ≥95%
（R1，基线模型）。关联 Track A/D。失败影响：步骤可读性 / 技能命中降级。

本脚本是**可运行的评测骨架**（directional spike，非 Wave-3 正式门槛）：
  1. 用 deepagents `skills=` 注入 N 个技能（progressive disclosure）；
  2. 注入一个带 `call_reason` 字段的工具，跑评测集，统计模型填 call_reason 的比例；
  3. 对每条评测 prompt 标注期望命中的技能，统计命中率。

判定（directional GREEN）：call_reason 填写率 ≥95% 且 skill 命中率 ≥95%。

运行：uv run --directory src/backend python scripts/035-linsight-deepagents/poc_p4_skill_call_reason.py [model_id]
依赖：一个**可用的中文 chat 模型**（DB 配置 + 有效凭证）。本机现有模型凭证失效 → 输出 BLOCKED。
设计真相：design §7（Skill 中间件）/ §3（call_reason 映射进 ExecStep.call_reason）。
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

# Make the backend source root importable when run as a script file.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from langchain_core.tools import tool
from pydantic import BaseModel, Field

# 评测集：prompt -> 期望命中的技能名（progressive disclosure 命中判定）
EVAL_SET = [
    {"prompt": "帮我分析这份季度财报的营收和净利润趋势。", "expect_skill": "financial-report"},
    {"prompt": "审一下这份采购合同里的付款与违约条款风险。", "expect_skill": "contract-review"},
    {"prompt": "把这段中文产品介绍翻译成地道英文。", "expect_skill": "translate"},
]

SKILLS = {
    "financial-report": "季度财报分析：抽取营收/净利润/同比，输出结构化报告。",
    "contract-review": "合同条款审阅：识别付款、违约、保密、争议解决条款的风险点。",
    "translate": "中英互译：保持术语一致与语气地道。",
}


class _ToolArgs(BaseModel):
    call_reason: str = Field(..., description="本步骤的简短中文标题，向用户解释这步在做什么")
    query: str = Field(..., description="工具输入")


@tool(args_schema=_ToolArgs)
def do_step(call_reason: str, query: str) -> str:
    """执行一个分析步骤。"""
    return f"done: {query}"


async def _resolve_model(model_id: int | None):
    """Return a usable BaseChatModel or None (BLOCKED) — probes DB-configured models."""
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.llm.domain.services.llm import ApplicationTypeEnum as AppEnum
    from bisheng.llm.domain.services.llm import BishengLLM

    set_current_tenant_id(1)
    candidates = [model_id] if model_id else [4, 5, 25, 26, 33, 35, 52, 55, 57, 58]
    for mid in candidates:
        if mid is None:
            continue
        try:
            llm = BishengLLM(
                model_id=mid, app_id=AppEnum.LINSIGHT.value, app_name="poc-p4", app_type=AppEnum.LINSIGHT, user_id=1
            )
            await asyncio.wait_for(llm.ainvoke("ping，请回复 ok"), timeout=30)
            print(f" - using model_id={mid}")
            return llm
        except Exception as exc:
            print(f" - model_id={mid} unusable: {repr(exc)[:90]}")
    return None


async def main() -> int:
    print("=== POC P4: call_reason 遵从率 + Skill 命中率 ===")
    model_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    llm = await _resolve_model(model_id)
    if llm is None:
        print(
            "\nRESULT P4: BLOCKED —— 无可用中文模型（DB 配置凭证失效）。"
            "脚本就绪，配置基线模型后即可跑；directional 验证下放 Wave 1，达标门槛 Wave 3。"
        )
        return 0

    from deepagents import create_deep_agent

    agent = create_deep_agent(model=llm, tools=[do_step], skills=SKILLS)

    call_reason_filled = 0
    call_reason_total = 0
    skill_hits = 0
    for case in EVAL_SET:
        result = await agent.ainvoke({"messages": [{"role": "user", "content": case["prompt"]}]})
        text = str(result)
        # call_reason fill rate: inspect tool calls in the message history
        for msg in result.get("messages", []):
            for tc in getattr(msg, "tool_calls", None) or []:
                if tc.get("name") == "do_step":
                    call_reason_total += 1
                    if (tc.get("args") or {}).get("call_reason"):
                        call_reason_filled += 1
        # skill hit: expected skill name surfaced in the trace
        if case["expect_skill"] in text:
            skill_hits += 1

    cr_rate = (call_reason_filled / call_reason_total) if call_reason_total else 0.0
    hit_rate = skill_hits / len(EVAL_SET)
    print(f" - call_reason 填写率: {call_reason_filled}/{call_reason_total} = {cr_rate:.0%}")
    print(f" - skill 命中率: {skill_hits}/{len(EVAL_SET)} = {hit_rate:.0%}")
    ok = cr_rate >= 0.95 and hit_rate >= 0.95
    print(f"\nRESULT P4: {'GREEN' if ok else 'RED'}（directional；正式 95% 门槛在 Wave 3，需更大评测集）")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
