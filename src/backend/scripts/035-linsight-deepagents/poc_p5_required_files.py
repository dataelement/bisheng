"""POC P5 — 中文模型对 code 工具 `required_files` 入参的声明遵从率 +
FileNotFoundError 提示后补声明的修复成功率。关联 Track C/A。
失败影响：大文件改无条件全量 push（牺牲 copy-in 耗时）。

可运行评测骨架（directional spike）：
  1. 注入 BiSheng 代码工具（args_schema 含 `required_files: list[str]`，见契约 C2）；
  2. 评测集：prompt 需读取一个 >SIZE_AUTOPUSH 的工作区文件，统计模型在 required_files 中声明该文件的比例；
  3. 对未声明的样本，回灌「需在 required_files 中声明」提示，统计补声明后修复成功率。

判定（directional GREEN）：首轮声明率 + 提示后修复率达到设计可接受阈值（Wave 3 定量）。

运行：uv run --directory src/backend python scripts/035-linsight-deepagents/poc_p5_required_files.py [model_id]
依赖：可用中文模型 **且** E2B 沙箱（config 无 e2b key）→ 现网 BLOCKED。
设计真相：design §9.3 / 契约 C2「代码工具入参契约」。
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

# Make the backend source root importable when run as a script file.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from langchain_core.tools import tool
from pydantic import BaseModel, Field

SIZE_AUTOPUSH_MB = 5  # >5MB 必须在 required_files 声明（沙箱不可达 MinIO，worker 中转）

EVAL_SET = [
    {
        "prompt": "用 pandas 读取工作区 scratch/big_dataset.csv（约 30MB），统计每列均值并写到 output/stats.csv。",
        "expect_required": "scratch/big_dataset.csv",
    },
    {
        "prompt": "加载 uploads/large_corpus/index.md（约 12MB）做词频统计，结果存 output/wordfreq.json。",
        "expect_required": "uploads/large_corpus/index.md",
    },
]


class _CodeArgs(BaseModel):
    code: str = Field(..., description="要在沙箱里运行的 Python 代码")
    required_files: list[str] = Field(
        default_factory=list,
        description=f"脚本需读取的工作区路径；>{SIZE_AUTOPUSH_MB}MB 的文件必须声明，否则沙箱内读不到。",
    )


@tool(args_schema=_CodeArgs)
def bisheng_code_interpreter(code: str, required_files: list[str]) -> str:
    """在 E2B 沙箱执行 Python 代码。大文件需在 required_files 声明，由 worker 中转写入沙箱。"""
    return "executed"


async def _resolve_model(model_id: int | None):
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
                model_id=mid, app_id=AppEnum.LINSIGHT.value, app_name="poc-p5", app_type=AppEnum.LINSIGHT, user_id=1
            )
            await asyncio.wait_for(llm.ainvoke("ping，请回复 ok"), timeout=30)
            print(f" - using model_id={mid}")
            return llm
        except Exception as exc:
            print(f" - model_id={mid} unusable: {repr(exc)[:90]}")
    return None


def _declared(result: dict, expect_path: str) -> bool:
    for msg in result.get("messages", []):
        for tc in getattr(msg, "tool_calls", None) or []:
            if tc.get("name") == "bisheng_code_interpreter":
                if expect_path in ((tc.get("args") or {}).get("required_files") or []):
                    return True
    return False


async def main() -> int:
    print("=== POC P5: required_files 声明遵从率 + 修复率 ===")
    model_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    llm = await _resolve_model(model_id)
    if llm is None:
        print(
            "\nRESULT P5: BLOCKED —— 无可用中文模型，且 config 未配置 E2B 沙箱。"
            "脚本就绪；directional 验证下放 Wave 1（Track C/A），达标门槛 Wave 3。"
        )
        return 0

    from deepagents import create_deep_agent

    agent = create_deep_agent(model=llm, tools=[bisheng_code_interpreter])

    first_declared = 0
    fixed_after_hint = 0
    need_fix = 0
    for case in EVAL_SET:
        res = await agent.ainvoke({"messages": [{"role": "user", "content": case["prompt"]}]})
        if _declared(res, case["expect_required"]):
            first_declared += 1
            continue
        # re-inject FileNotFoundError hint and re-ask
        need_fix += 1
        hint = f"运行报错 FileNotFoundError: {case['expect_required']}。请在 required_files 中声明该文件后重试。"
        res2 = await agent.ainvoke(
            {
                "messages": [
                    {"role": "user", "content": case["prompt"]},
                    {"role": "user", "content": hint},
                ]
            }
        )
        if _declared(res2, case["expect_required"]):
            fixed_after_hint += 1

    n = len(EVAL_SET)
    print(f" - 首轮声明率: {first_declared}/{n} = {first_declared / n:.0%}")
    if need_fix:
        print(f" - 提示后修复率: {fixed_after_hint}/{need_fix} = {fixed_after_hint / need_fix:.0%}")
    print("\nRESULT P5: directional（正式门槛在 Wave 3，需更大评测集 + 真 E2B）")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
