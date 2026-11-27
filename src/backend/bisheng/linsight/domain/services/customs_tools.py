# ruff: noqa: RUF001
"""D customs tool: trusted private API -> WorkspaceBackend -> fixed Skill code."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sys
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, ConfigDict, Field, SkipValidation, model_validator

NAME = "customs_history"
MARKER = "__BISHENG_CUSTOMS_FINAL_V1__"
PROTOCOL = "customs-fixed-entry-v1"
CLIENT = Path("/app/customs-runtime/platform_fetch.py")
CONFIG = Path("/app/customs-private/client.json")
FAILURE = "报关工具未能完成本轮处理，已停止；本次失败不表示没有历史费用。"


class Conditions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    house_numbers: list[str] | None = None
    bill_numbers: list[str] | None = None
    contract_numbers: list[str] | None = None
    master_numbers: list[str] | None = None
    material_code: str | None = None
    destination_code: str | None = None
    model: str | None = None
    destination: str | None = None
    dangerous_goods: str | None = None
    carrier: str | None = None
    currency: str | None = None
    gross_weight_kg: float | None = None
    length_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None
    package_count: int | None = None
    date_field: Literal["history_date"] | None = None
    date_from: str | None = None
    date_to: str | None = None


class Weight(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: float
    unit: str


class Packaging(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    length: float | None = None
    width: float | None = None
    height: float | None = None
    unit: str | None = None
    count: int | None = None


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str | None = None
    destination: str | None = None
    dangerous_goods: str | None = None
    carrier: str | None = None
    currency: str | None = None
    gross_weight_kg: float | None = None
    length_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None
    package_count: int | None = None
    date_field: Literal["history_date"] | None = None
    date_from: str | None = None
    date_to: str | None = None
    gross_weight: Weight | None = None
    packaging: Packaging | None = None


class CustomsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["history", "inquiry", "show", "filter", "reset", "detail", "explain_limits"]
    query: Conditions | None = None
    target: Target | None = None
    set: Conditions | None = None
    unset: list[str] | None = None
    sort: Literal["source", "history_date_asc", "history_date_desc"] | None = None
    page: int | None = None
    page_size: int | None = None
    reference: str | None = None
    query_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def ignore_unknown_nulls(cls, value):
        # Preserve the compatibility demonstrated by the procurement provider.
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k in cls.model_fields or v is not None}
        return value


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request: CustomsRequest = Field(
        description="一次传齐本轮报关动作与全部条件/排序。history查分单或账单，inquiry推荐报关代理并找报关参考；续问show/filter/reset/detail。不传Python、网址、工作区或API回执。"
    )


def normalize_request(request):
    if isinstance(request, BaseModel):
        request = request.model_dump(exclude_unset=True, exclude_none=True)
    request = dict(request)
    # Fresh queries always start at page one. Provider may explicitly echo it.
    # Do not discard non-default pages or coerce boolean/float values.
    if request.get("action") in ("history", "inquiry") and type(request.get("page")) is int and request["page"] == 1:
        request.pop("page")
    return request


def execution_code(request: dict) -> str:
    raw = json.dumps(request, ensure_ascii=False, allow_nan=False)
    if len(raw.encode()) > 65536:
        raise ValueError("request budget")
    return (
        "import importlib.util,json,sys\nfrom pathlib import Path\n"
        "_path=Path('skills/customs-history/scripts/customs.py')\n"
        "sys.path.insert(0,str(_path.parent))\n"
        "_spec=importlib.util.spec_from_file_location('customs_fixed_entry',_path)\n"
        "_module=importlib.util.module_from_spec(_spec)\n"
        "sys.modules[_spec.name]=_module\n_spec.loader.exec_module(_module)\n"
        "_request=json.loads(" + repr(raw) + ")\n"
        "_binding_error=False\n"
        "if _request.get('action')=='detail' and 'query_id' not in _request:\n"
        "    try:\n"
        "        with _module.locked(Path.cwd()):\n"
        "            _state=_module.read(_module.safe(Path.cwd(),_module.STATE))[1]\n"
        "            _module.validate_state(_state)\n"
        "            _request['query_id']=_state['query_id']\n"
        "    except Exception:\n"
        "        _binding_error=True\n"
        "_result=(_module.final('state_error',_module.MESSAGES['state_error']) if _binding_error else _module.run(_request,Path.cwd()))\n"
        "print(" + repr(MARKER) + "+json.dumps(_result,ensure_ascii=False,allow_nan=False))\n"
    )


def execution_result(raw: Any) -> dict:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict) or raw.get("exitcode") != 0 or not isinstance(raw.get("log"), str):
        raise ValueError("executor failed")
    lines = [line[len(MARKER) :] for line in raw["log"].splitlines() if line.startswith(MARKER)]
    if len(lines) != 1:
        raise ValueError("completion record")
    result = json.loads(lines[0])
    if (
        not isinstance(result, dict)
        or result.get("protocol") != PROTOCOL
        or result.get("terminal") is not True
        or result.get("next_action") != "none"
        or result.get("status") not in ("final", "user_clarification")
        or not isinstance(result.get("answer"), str)
        or not 0 < len(result["answer"].encode()) <= 131072
    ):
        raise ValueError("completion contract")
    return result


async def fetch_and_upload(request: dict, workspace: Any) -> list:
    with tempfile.TemporaryDirectory(prefix="customs-api-") as directory:
        root = Path(directory)
        path = root / "request.json"
        path.write_text(json.dumps({"request": request}, ensure_ascii=False))
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(CLIENT),
            "--request-file",
            str(path),
            "--workspace",
            str(root),
            "--config",
            str(CONFIG),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=70)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode != 0 or len(stdout) > 65536:
            raise ValueError("API fetch failed")
        receipt = json.loads(stdout)
        pages = receipt.get("receipts")
        if receipt.get("status") != "customs_pages_saved" or not isinstance(pages, list) or not 1 <= len(pages) <= 100:
            raise ValueError("API receipt failed")
        uploads = []
        total = 0
        for page in pages:
            name = page.get("path")
            if not isinstance(name, str) or not re.fullmatch(r"uploads/customs-api/[a-f0-9]{32}\.json", name):
                raise ValueError("receipt path")
            raw = (root / name).read_bytes()
            total += len(raw)
            if (
                total > 16 * 1024 * 1024
                or len(raw) != page.get("bytes")
                or hashlib.sha256(raw).hexdigest() != page.get("sha256")
            ):
                raise ValueError("receipt integrity")
            uploads.append(("/" + name, raw))
        results = await workspace.aupload_files(uploads)
        if len(results) != len(uploads) or any(
            r.error or r.path != expected[0] for r, expected in zip(results, uploads, strict=True)
        ):
            raise ValueError("workspace persistence failed")
        return pages


class CustomsTool(BaseTool):
    name: str = NAME
    description: str = (
        "报关代理推荐与历史费用唯一固定入口。history仅按query查历史费用与代理，不附推荐；inquiry仅在用户明确要求推荐时按target为新报关推荐代理（排序+首选）并给历史参考，用户要推荐代理/报关方案时用inquiry。"
        "询价需要目的港、型号、毛重KG、长宽高CM及危化属性，缺失时传已知字段，工具返回澄清。"
        "首次同时传齐set筛选、sort排序；show/filter/reset/detail续问，detail传reference；query_id可省略，由执行端从本Chat已验证状态绑定当前查询；明确提供的旧query_id仍拒绝。"
        "用户要求分摊/每公斤价格/本次正式报价，或推断账单作废/差额责任时，仅调用explain_limits（只传action），由固定代码说明已知边界。"
        "正常查询历史业务日期仍用history/inquiry。工具直接返回即结束，不自由扩写。"
    )
    args_schema: Annotated[ArgsSchema | None, SkipValidation()] = ToolInput
    return_direct: bool = True
    response_format: Literal["content_and_artifact"] = "content_and_artifact"
    inner: BaseTool = Field(exclude=True, repr=False)
    workspace: Any = Field(exclude=True, repr=False)

    def _run(self, *args, **kwargs):
        raise NotImplementedError("async customs tool only")

    async def _fixed(self, request, config):
        return execution_result(await self.inner.ainvoke({"python_code": execution_code(request)}, config=config))

    async def _arun(self, request: dict, config: RunnableConfig | None = None):
        phase = "public_request"
        try:
            request = normalize_request(request)
            if request["action"] == "inquiry":
                phase = "inquiry_fixed"
                result = await self._fixed(request, config)
                if result.get("outcome") == "needs_new_query":
                    phase = "inquiry_fetch_upload"
                    pages = await fetch_and_upload(request, self.workspace)
                    phase = "inquiry_import"
                    result = await self._fixed({**request, "receipts": pages}, config)
            elif request["action"] == "history":
                phase = "history_fetch_upload"
                pages = await fetch_and_upload(request, self.workspace)
                phase = "history_import"
                result = await self._fixed({**request, "receipts": pages}, config)
            else:
                phase = "continuation_fixed"
                result = await self._fixed(request, config)
        except Exception as error:
            # Operator diagnostics contain no values, arguments, headers or exception text.
            logging.getLogger(__name__).warning(
                "customs_failure phase=%s type=%s keys=%s",
                phase,
                type(error).__name__,
                ",".join(sorted(request)) if isinstance(request, dict) else "invalid",
            )
            result = {
                "protocol": PROTOCOL,
                "status": "final",
                "outcome": "execution_error",
                "terminal": True,
                "next_action": "none",
                "answer": FAILURE,
            }
        # Keep compact query_id/bills in the model context for later F references.
        result["answer"] = business_process("customs", request, result)
        artifact = {"protocol": PROTOCOL, "terminal": True, "next_action": "none", "answer": result["answer"]}
        return json.dumps(result, ensure_ascii=False), artifact


def bind_customs_tools(tools, backend, selected_skills=None):
    if not isinstance(selected_skills, list) or "customs-history" not in selected_skills:
        return tools
    if any(isinstance(t, CustomsTool) for t in tools):
        return tools
    code = next((t for t in tools if getattr(t, "name", None) == "bisheng_code_interpreter"), None)
    if code is None:
        return tools
    # A simultaneous procurement selection must not pass its JSON wrapper as Python.
    if type(code).__name__ == "ProcurementExecutionTool":
        code = code.inner
    result = list(tools)
    if "procurement-history" not in selected_skills:
        result = [t for t in result if getattr(t, "name", None) != "bisheng_code_interpreter"]
    return [*result, CustomsTool(inner=code, workspace=backend)]


def extract_customs_completion(messages):
    if not isinstance(messages, (list, tuple)) or not messages:
        return None
    last = messages[-1]
    name = last.get("name") if isinstance(last, dict) else getattr(last, "name", None)
    kind = last.get("type", last.get("role")) if isinstance(last, dict) else getattr(last, "type", None)
    if name != NAME or kind != "tool":
        return None
    a = last.get("artifact") if isinstance(last, dict) else getattr(last, "artifact", None)
    if (
        not isinstance(a, dict)
        or a.get("protocol") != PROTOCOL
        or a.get("terminal") is not True
        or a.get("next_action") != "none"
        or not isinstance(a.get("answer"), str)
        or not 0 < len(a["answer"].encode()) <= 131072
    ):
        return FAILURE
    return a["answer"]


class CustomsMiddleware(AgentMiddleware):
    @staticmethod
    def _serial(state):
        messages = state.get("messages") or []
        if not messages or not isinstance(messages[-1], AIMessage):
            return None
        last = messages[-1]
        calls = [c for c in last.tool_calls if c.get("name") == NAME]
        if not calls or len(last.tool_calls) == 1:
            return None
        call = dict(calls[0])
        if len(calls) > 1:
            call["args"] = {"request": {"action": "__parallel_not_supported__"}}
        return {"messages": [last.model_copy(update={"tool_calls": [call], "invalid_tool_calls": []})]}

    def after_model(self, state, runtime):
        return self._serial(state)

    async def aafter_model(self, state, runtime):
        return self._serial(state)

    def wrap_model_call(self, request, handler):
        answer = extract_customs_completion(request.state.get("messages"))
        return ModelResponse(result=[AIMessage(content=answer)]) if answer is not None else handler(request)

    async def awrap_model_call(self, request, handler):
        answer = extract_customs_completion(request.state.get("messages"))
        return ModelResponse(result=[AIMessage(content=answer)]) if answer is not None else await handler(request)


# Generated from assistant-workbench/process_summary.py
"""A bounded, source-backed business execution recap, never model internal reasoning.

This pure function is embedded into the three already-mounted tool adapters by
build_release.py. It does not modify the underlying business answer or compute fees.
"""


def business_process(scene, request, result):
    import json

    if not isinstance(request, dict) or not isinstance(result, dict):
        return result.get("answer", "") if isinstance(result, dict) else ""
    answer = result.get("answer", "")
    if not isinstance(answer, str) or not answer:
        return answer
    if answer.startswith("```business-process\n"):
        return answer
    action = request.get("action", "show")
    outcome = result.get("outcome", "unknown")
    names = {"procurement": "采购", "transport": "运输", "customs": "报关"}
    nodes = []

    def add(title, summary, status="done", details=None):
        nodes.append(
            {
                "title": title,
                "summary": str(summary)[:500],
                "status": status,
                "details": [str(x)[:600] for x in (details or [])][:8],
            }
        )

    labels = {
        "model": "规格型号",
        "target_model": "当前型号",
        "purchaser": "本次甲方",
        "origin": "起点",
        "destination": "目的地",
        "mode": "运输方式",
        "dangerous_goods": "危化属性",
        "net_weight_kg": "净重kg",
        "gross_weight_kg": "毛重kg",
        "house_numbers": "分单号",
        "bill_numbers": "账单号",
        "date_from": "起始日期",
        "date_to": "截止日期",
        "currency": "币种",
        "carrier": "服务商",
        "sort": "排序",
        "reference": "费用引用",
        "supplier_name": "询价对象",
    }
    conditions = []
    for source in [request, request.get("query"), request.get("target"), request.get("set")]:
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if key in labels and value is not None:
                conditions.append(labels[key] + "：" + str(value)[:160])
    action_names = {
        "history": "历史查询",
        "suppliers": "供应商选取",
        "compare": "记录比价",
        "filter": "条件筛选",
        "reset": "恢复条件",
        "show": "查看结果",
        "inquiry": "寻找历史参考",
        "detail": "单据追溯",
        "confirm": "确认询价对象",
        "unconfirm": "撤销确认",
        "confirmations": "查看确认记录",
        "choose": "选择近似型号",
        "resolve": "型号核对",
        "help": "输入引导",
        "explain_limits": "说明数据边界",
    }
    add("理解本轮需求", action_names.get(action, "按本轮要求处理"), details=conditions)
    failed = outcome in {
        "execution_error",
        "source_unavailable",
        "state_error",
        "validation_error",
        "invalid_request",
        "stale_source",
        "stale_reference",
        "query_error",
        "invalid_query",
        "file_or_state_error",
        "api_failure",
        "api_error",
        "api_timeout",
        "invalid_filter",
        "invalid_regex",
    }
    waiting = result.get("status") == "user_clarification" or outcome in {
        "needs_clarification",
        "needs_input",
        "needs_query",
        "needs_new_query",
        "needs_correction",
        "pending_correction",
        "pending_candidates",
        "awaiting_correction",
        "awaiting_selection",
        "no_exact_match",
        "invalid_selection",
        "page_out_of_range",
    }
    if scene == "procurement" and "请核对是否需要修正" in answer:
        waiting = True
    empty = outcome in {"no_records", "no_exact_history", "no_history"}
    if failed:
        add("本轮处理未完成", "本次失败不能解释为没有历史记录", "error", [answer[:450]])
        add("恢复处理", "请按错误提示重试或补充；未获得的数据不作结论", "pending")
    elif scene == "procurement":
        models = result.get("models") or []
        if isinstance(models, list) and models:
            if "型号差异：原始目标为" in answer:
                add(
                    "按确认执行近似召回",
                    "返回" + str(len(models[:3])) + "个近似型号，按型号分别展示",
                    details=["型号：" + str(m.get("model", "")) for m in models[:3] if isinstance(m, dict)]
                    + ["规格差异和可替代性尚未核验，不合并不同型号价格"],
                )
            for model in models[:3]:
                if not isinstance(model, dict):
                    continue
                c = model.get("counts") or {}
                sc = model.get("supplier_counts") or {}
                add(
                    "核对历史与筛选",
                    str(model.get("model", "当前型号"))
                    + " · 原批次"
                    + str(c.get("original_batch_records", 0))
                    + "条，当前匹配"
                    + str(c.get("total_matches", 0))
                    + "条",
                    "empty" if not c.get("total_matches") else "done",
                    [
                        "生效筛选：" + json.dumps(model.get("active_filters", {}), ensure_ascii=False),
                        "本次数据已由固定执行入口校验；价格按型号分别展示",
                    ],
                )
                recommendation_in_answer = model.get("view") == "history" and "**供应商推荐" in answer
                if (
                    model.get("view") == "suppliers"
                    or sc.get("historical_supplier_groups", 0)
                    or recommendation_in_answer
                ):
                    buyer = model.get("purchaser") or request.get("purchaser")
                    if buyer in ["空客", "空中客车", "Airbus", "airbus", "商飞", "中国商飞", "COMAC", "comac"]:
                        name = "QPL" if buyer in ["空客", "空中客车", "Airbus", "airbus"] else "QSL"
                        recap = (
                            "已依据" + name + "名单生成本轮推荐；具体候选与证据见下方"
                            if recommendation_in_answer
                            else "历史条件组"
                            + str(sc.get("historical_supplier_groups", 0))
                            + "项 · 保留"
                            + str(sc.get("total_items", 0))
                            + "项 · 排除或待核验"
                            + str(sc.get("excluded_supplier_groups", 0))
                            + "项"
                        )
                        add(
                            "按甲方核验 " + name,
                            recap,
                            "done",
                            [
                                "名单命中、未列入、待核验分别按实际结果显示",
                                "所给版本的主体和产品适用范围见业务结果中的名录证据",
                            ],
                        )
                    else:
                        add("核对名录要求", "本次甲方未指定，或按现有范围无需核验名录", "skipped")
            add(
                "形成本轮结果",
                "按生效条件展示；价格排序与可比口径详见下方",
                details=["沿用用户当前排序和筛选，不生成新的报价或交付指标"],
            )
        elif action in ["confirm", "unconfirm", "confirmations"]:
            add(
                "更新本对话确认记录",
                {"confirm": "记录本次询价对象", "unconfirm": "撤销本次确认", "confirmations": "读取已有确认记录"}[
                    action
                ],
                details=["记录仅限本对话，不向订单系统下单"],
            )
        elif waiting or empty:
            add(
                "核对型号与可用数据",
                "需要补充或选择后继续；具体原因见下方",
                "waiting" if waiting else "empty",
                [answer[:450]],
            )
        else:
            add("执行本轮处理", "固定入口已返回本轮结果", details=["动作：" + str(action), "结果状态：" + str(outcome)])
        if waiting:
            add("等待你确认或补充", "后续步骤暂停，按下方提示回复即可", "waiting")
        elif empty:
            add("本轮查询无匹配", "仅针对当前取数范围和条件，不表示全部历史无记录", "empty")
        elif action not in ["confirm", "unconfirm", "confirmations"]:
            add("查看与继续", "可继续筛选、比较或确认询价对象")
    else:
        if waiting:
            add("核对必要条件", "需要补齐条件后继续匹配", "waiting", [answer[:450]])
            add("等待你补充", "尚未完成匹配和费用判断", "pending")
        elif outcome == "capability_limits":
            add("核对数据边界", "当前能力与缺失项见下方说明")
        else:
            match = result.get("match") or {}
            counts = result.get("counts") or {}
            kind = match.get("match_type", "history")
            history_empty = empty or kind == "no_records"
            recommendations = result.get("recommendation") or []
            if isinstance(recommendations, list) and recommendations:
                tiers = [r.get("tier", 0) for r in recommendations if isinstance(r, dict)]
                cross = bool(tiers) and min(tiers) >= 3
                add(
                    "整理" + ("运输方案" if scene == "transport" else "报关代理") + "候选",
                    str(len(recommendations))
                    + "项"
                    + ("相近经验推荐；当前硬条件没有历史匹配" if history_empty else "历史经验推荐"),
                    details=["跨线路或目的港经验只用于候选参考，不作为当前硬条件命中的费用"]
                    if cross
                    else ["推荐依据和历史金额口径见下方；不构成本次正式报价"],
                )
            labels_match = {
                "history": "按单据与条件查询历史",
                "full": "完整条件匹配",
                "approximate": "近似条件匹配",
                "no_records": "当前条件暂无匹配",
            }
            add(
                "核对查询与匹配",
                labels_match.get(kind, "按当前条件匹配"),
                "empty" if history_empty else "done",
                [
                    "保护条件："
                    + ("线路、运输方式、危化属性" if scene == "transport" else "目的港、危化属性；重量采用毛重口径"),
                    "逐级匹配步骤：" + json.dumps(match.get("steps", []), ensure_ascii=False)[:550],
                ],
            )
            if result.get("reference_strength") == "protected_only":
                add(
                    "核对参考强度",
                    "仅保护条件命中，物料、重量和尺寸均未匹配；属于弱参考",
                    details=["历史总额不构成本次正式报价，不能将弱匹配讲成同条件价格"],
                )
            if counts:
                add(
                    "核对费用与完整覆盖",
                    str(counts.get("matched_details", 0))
                    + "条命中明细 · "
                    + str(counts.get("unique_bills", 0))
                    + "张去重账单",
                    "empty" if history_empty else "done",
                    ["共享账单按完整覆盖展示，总额去重，不自动分摊", "金额、币种、日期及匹配差异见业务结果"],
                )
            add(
                "展示" + ("单据详情" if action == "detail" else "历史参考"),
                "当前硬条件无历史匹配；候选推荐另行说明"
                if history_empty
                else "结果与依据已返回，可继续查看详情或调整条件",
                "empty" if history_empty else "done",
            )
    demo = any(
        str(v).startswith("DEMO-Q")
        for v in [
            request.get("model"),
            request.get("target_model"),
            *[m.get("model") for m in result.get("models", []) if isinstance(m, dict)],
        ]
    )
    payload = {
        "version": 1,
        "scene": scene,
        "title": names.get(scene, "业务") + "分析过程",
        "action": action,
        "outcome": outcome,
        "mode": "execution_recap",
        "demo": demo,
        "conditions": conditions[:12],
        "nodes": nodes[:12],
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("`", "\\u0060")
    return (
        "```business-process\n"
        + encoded
        + "\n```\n\n"
        + ("> 模拟演示数据：型号、订单、价格与日期为合成；名单证据引用所提供版本。\n\n" if demo else "")
        + answer
    )
