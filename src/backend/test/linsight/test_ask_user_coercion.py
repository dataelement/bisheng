"""Regression: ``ask_user`` must tolerate models that stringify ``questions``.

Root cause (observed live with model qwen3.7-max, session 8b9529fc...): the model
correctly intends to call ``ask_user`` to clarify, but its OpenAI-compatible
function-calling serializer emits the nested ``questions`` array as a JSON
*string* (``'[{"question": ...}]'``). Strict ``list[dict]`` validation rejected it
with "questions: Input should be a valid list" BEFORE the tool body ran, so the
model retried the identical malformed call three times and then gave up — the
task never parked (session went straight to COMPLETED).

The fix widens the arg to ``list[dict] | str | None`` and runs ``_coerce_questions``
so a stringified payload (whole array, or per-item) is parsed back into a clean
``list[dict]``, degrading to ``[]`` (park with reason only) rather than ever
hard-failing the HITL flow. These tests pin that behavior deterministically.
"""

from unittest.mock import MagicMock, patch

from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.agent_factory import (
    _EMPTY_QUESTIONS_RETRY_HINT,
    _EMPTY_QUESTIONS_RETRY_MARKER,
    _coerce_questions,
    _empty_retry_count,
    _salvage_options_only,
    ask_user,
)

# The exact kwargs qwen3.7-max sent (and that strict validation rejected) in the
# live session — `questions` is a JSON STRING, not a list.
_LIVE_FAILING_QUESTIONS_STR = (
    '[{"question": "报告希望覆盖哪些粮食品种？", '
    '"options": ["主要谷物（玉米、小麦、大豆）", "全品种", "仅大豆和玉米"], "multiple": false}, '
    '{"question": "报告输出格式？", '
    '"options": ["Markdown", "Markdown + Word (.docx)", "Markdown + PDF"], "multiple": true}]'
)


# --- _coerce_questions pure-function behavior -------------------------------


def test_coerce_stringified_array():
    """The whole array stringified -> parsed back into list[dict]."""
    out = _coerce_questions(_LIVE_FAILING_QUESTIONS_STR)
    assert isinstance(out, list)
    assert len(out) == 2
    assert out[0]["question"] == "报告希望覆盖哪些粮食品种？"
    assert out[1]["multiple"] is True
    assert "Markdown" in out[1]["options"]


def test_coerce_stringified_items():
    """A real list whose items are each stringified -> per-item parse."""
    value = [
        '{"question": "Q1", "options": ["a", "b"], "multiple": false}',
        '{"question": "Q2", "options": [], "multiple": false}',
    ]
    out = _coerce_questions(value)
    assert len(out) == 2
    assert out[0]["question"] == "Q1"
    assert out[0]["options"] == ["a", "b"]


def test_coerce_plain_string_item_becomes_open_question():
    """A non-JSON string item is wrapped as an open-ended question, not dropped."""
    out = _coerce_questions(["请输入你的预算"])
    assert out == [{"question": "请输入你的预算"}]


def test_coerce_passthrough_well_formed_list():
    """A correctly-typed list[dict] is returned unchanged in content."""
    value = [{"question": "Q", "options": ["x"], "multiple": False}]
    out = _coerce_questions(value)
    assert out == value


def test_coerce_degrades_to_empty():
    """Unparseable / empty / wrong-type inputs degrade to [] (never raise)."""
    assert _coerce_questions(None) == []
    assert _coerce_questions("") == []
    assert _coerce_questions("   ") == []
    assert _coerce_questions("not json at all") == []
    assert _coerce_questions("{not: valid}") == []
    assert _coerce_questions(42) == []
    assert _coerce_questions('{"question": "single object not array"}') == []  # dict, not list


# The harder live failure (session 9aef4773…, 福建古田7日游): the model crammed the
# WHOLE 4-question array into ONE list element, dropped its opening `[{"question": "`,
# and left inner quotes unescaped ("你指的"古田"是哪一个？"). json.loads fails, so the
# OLD code wrapped the entire ~500-char blob as a single bogus question whose TEXT was
# raw JSON (the user saw `..., "options": [...], "multiple": false}, {"question": ...`).
# json_repair-based recovery now reconstructs the structured questions.
_MALFORMED_ARRAY_CRAMMED = (
    '你 "你指的"古田"是哪一个？", "options": ["龙岩·上杭古田镇", "宁德·古田县", "两个都串联", "不确定，请推荐"], '
    '"multiple": false}, {"question": "出发城市与交通方式？", "options": ["从福州出发", "从厦门出发", "从其他城市"], '
    '"multiple": false}, {"question": "你希望输出什么格式？", "options": ["仅 markdown", "markdown + Word"], '
    '"multiple": true}]'
)


def test_coerce_malformed_crammed_array_is_never_a_raw_blob():
    """The CONTRACT (the reported bug's fix): a whole array crammed into one
    malformed-JSON string element must NEVER be dumped as a single bogus question
    whose text is raw JSON. It is either RECOVERED into clean structured questions
    (best-effort via json_repair — input/version-sensitive, so not asserted by
    exact count) or DROPPED — but never a raw blob.

    Note we assert the invariant, not the recovery count: json_repair is byte-
    sensitive (the live DB blob recovers all 4 in the deployed env; a hand-typed
    near-copy may recover fewer or none) — the guarantee that holds regardless is
    "no raw blob". On the OLD code this element became one ~500-char 'question'.
    """
    out = _coerce_questions([_MALFORMED_ARRAY_CRAMMED])
    # the old failure was exactly: len==1 with a giant raw-JSON question text
    assert not (len(out) == 1 and len(str(out[0].get("question", ""))) > 200)
    # whatever survives is a clean question dict with non-empty question text
    assert all(isinstance(q, dict) and str(q.get("question", "")).strip() for q in out)


def test_coerce_drops_unrecoverable_debris_not_a_blob():
    """A structured-looking element with no question text yields nothing — it is
    dropped, never surfaced to the user as a raw-JSON 'question'. Deterministic
    (json.loads only; the opening-bracket restore is skipped for a string that
    already starts with '{')."""
    assert _coerce_questions(['{"options": ["a", "b"], "multiple": false}']) == []


# --- ask_user tool: the stringified payload must now park, not ValidationError


async def test_ask_user_accepts_stringified_questions_and_parks():
    """Reproduce the live failure: ask_user.ainvoke with `questions` as a JSON
    string must NOT raise a validation error and must park with both questions."""
    captured = MagicMock(return_value="<resume-sentinel>")
    with patch.object(agent_factory, "interrupt", captured):
        result = await ask_user.ainvoke(
            {"reason": "为了产出最合适的北美粮食报告，需要确认以下信息：", "questions": _LIVE_FAILING_QUESTIONS_STR}
        )

    assert result == "<resume-sentinel>"
    captured.assert_called_once()
    payload = captured.call_args.args[0]
    tool_calls = payload["params"]["tool_calls"]
    assert len(tool_calls) == 2
    assert all(tc["name"] == "clarify" for tc in tool_calls)
    assert tool_calls[0]["args"]["question"] == "报告希望覆盖哪些粮食品种？"
    assert tool_calls[1]["args"]["multiple"] is True
    assert "Markdown" in tool_calls[1]["args"]["options"]


async def test_ask_user_empty_questions_nudges_once_before_parking():
    """① self-heal: the FIRST call with unusable questions returns the corrective
    hint as a normal tool result (so the agent loop continues and the model re-calls
    WITH structure) and does NOT park yet. This is the fix for the live screenshot:
    the model listed the questions in its reasoning but sent an empty `questions`."""
    captured = MagicMock(return_value="ok")
    with patch.object(agent_factory, "interrupt", captured):
        result = await ask_user.ainvoke({"reason": "需要澄清", "questions": "garbage-not-json"})

    captured.assert_not_called()  # no park yet — give the model a chance to fix
    assert result == _EMPTY_QUESTIONS_RETRY_HINT
    assert _EMPTY_QUESTIONS_RETRY_MARKER in result


async def test_ask_user_empty_questions_parks_after_one_nudge():
    """① cap: once we have already nudged THIS turn (a prior corrective ToolMessage
    is in the history), a still-empty call degrades to a reason-only free-text park —
    never an infinite retry. This is the 2026-06-22 no-infinite-retry guarantee."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    state = {
        "messages": [
            HumanMessage(content="帮我做个东西"),
            AIMessage(content="", tool_calls=[{"id": "a", "name": "ask_user", "args": {}}]),
            ToolMessage(content=_EMPTY_QUESTIONS_RETRY_HINT, tool_call_id="a"),
        ]
    }
    captured = MagicMock(return_value="ok")
    with patch.object(agent_factory, "interrupt", captured):
        await ask_user.ainvoke({"reason": "需要澄清", "questions": "garbage-not-json", "state": state})

    captured.assert_called_once()
    payload = captured.call_args.args[0]
    assert payload["reason"] == "需要澄清"
    assert payload["params"]["tool_calls"] == []


async def test_ask_user_options_only_salvaged_renders_options():
    """② the model gave option lists but forgot the question text → keep the options
    under a neutral placeholder title (a renderable, clickable card instead of a blank
    free-text box, no wasted retry). The model's `reason` stays the card header, so
    the body title must NOT repeat it — it uses the neutral placeholder instead."""
    captured = MagicMock(return_value="ok")
    questions = [{"options": ["北美", "全球", "仅中国"], "multiple": False}]
    with patch.object(agent_factory, "interrupt", captured):
        await ask_user.ainvoke({"reason": "请确认报告范围", "questions": questions})

    captured.assert_called_once()
    payload = captured.call_args.args[0]
    assert payload["reason"] == "请确认报告范围"  # header keeps the reason
    tool_calls = payload["params"]["tool_calls"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["args"]["question"] == "请从以下选项中选择"  # neutral — no duplication
    assert tool_calls[0]["args"]["options"] == ["北美", "全球", "仅中国"]


async def test_ask_user_well_formed_list_unchanged():
    """The well-behaved path (proper list[dict]) keeps working."""
    captured = MagicMock(return_value="ok")
    questions = [{"question": "Q", "options": ["a", "b"], "multiple": False}]
    with patch.object(agent_factory, "interrupt", captured):
        await ask_user.ainvoke({"reason": "r", "questions": questions})

    tool_calls = captured.call_args.args[0]["params"]["tool_calls"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["args"]["options"] == ["a", "b"]


# --- ② _salvage_options_only pure-function behavior -------------------------


def test_salvage_options_only_picks_options_dicts():
    """An options-only dict is recovered under the neutral placeholder title (NOT the
    reason, which is already the card header — avoids on-screen duplication)."""
    out = _salvage_options_only([{"options": ["a", "b"], "multiple": True}])
    assert out == [{"question": "请从以下选项中选择", "options": ["a", "b"], "multiple": True}]


def test_salvage_skips_question_bearing_and_pure_debris():
    """Question-bearing items (already kept by _coerce_questions) and pure debris
    (neither question nor options) are NOT salvaged."""
    assert _salvage_options_only([{"question": "Q", "options": ["a"]}]) == []
    assert _salvage_options_only([{"foo": "bar"}]) == []
    assert _salvage_options_only([{"options": []}]) == []  # empty options dropped


# --- ① _empty_retry_count pure-function behavior ----------------------------


def test_empty_retry_count_none_and_no_marker():
    """Missing / None / marker-free state allows the nudge (count 0)."""
    assert _empty_retry_count(None) == 0
    assert _empty_retry_count({}) == 0
    assert _empty_retry_count({"messages": []}) == 0
    assert _empty_retry_count({"messages": [{"type": "tool", "content": "ok"}]}) == 0


def test_empty_retry_count_detects_prior_nudge():
    """A prior corrective ToolMessage this turn counts as one nudge (caps the loop)."""
    state = {"messages": [{"type": "tool", "content": _EMPTY_QUESTIONS_RETRY_HINT}]}
    assert _empty_retry_count(state) == 1


def test_empty_retry_count_resets_on_new_human_turn():
    """A fresh user turn (human message) re-arms the nudge so each turn self-heals."""
    state = {
        "messages": [
            {"type": "tool", "content": _EMPTY_QUESTIONS_RETRY_HINT},
            {"type": "human", "content": "新一轮请求"},
        ]
    }
    assert _empty_retry_count(state) == 0


# --- ③ system prompt carries a concrete filled questions example ------------


def test_system_prompt_contains_filled_questions_example():
    """The ③ few-shot must survive in the rendered prompt (both KB variants) so the
    model has a copy-pasteable structured-questions template to anchor on."""
    from bisheng.linsight.domain.services.agent_factory import _build_linsight_system_prompt

    for has_kb in (True, False):
        prompt = _build_linsight_system_prompt(has_knowledge_base=has_kb)
        assert "正确示例" in prompt
        assert '"multiple": true' in prompt
