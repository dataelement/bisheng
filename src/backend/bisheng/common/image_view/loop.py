"""Vision-loop helpers: pick ids, drop catalog history, inject/override view_image calls."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage
from loguru import logger

from bisheng.common.image_view.annotate import ImageRegistry
from bisheng.common.image_view.tool import MAX_IMAGES_PER_TURN, TOOL_NAME

IMAGE_VIEW_PROMPT_RULES = """# 查看图片
1. `⟦img#N⟧` 只是锚点，第一次请求看不见像素。文件名、alt、上下文、上一轮回答都不是图里的内容。
2. 用户问截图 / 界面 / 表单字段 / 图内文字 / 图表走势时，必须先调 `view_image`（`image_ids` 为列表，单轮最多 3 张），看完再答。
3. 选图：根据问题匹配附近标题 / 说明文字对应的 `img#`，不要默认第一张 `img#1`。
4. 不要写「我看不到图」，不要根据周围文字或历史编造图意。
5. 回答里仍输出原始 `![](url)`，方便前端渲染。
6. 只能使用本轮出现过的 `img#`。"""

# Prior assistant turns that list many img# ids were almost always guessed from
# filenames / surrounding text (no pixels). Keep short answers that cite 1–3 images.
_CATALOG_IMG_MENTIONS = 5
_NEED_PIXELS = re.compile(r"截图|界面|表单|字段|图里|走势|图表|这张图|图片写|看图|图上")
_USER_QUESTION_MARKERS = ("# 用户问题", "# User question")
_ANCHOR_RE = re.compile(r"\u27e6(img#\d+)\u27e7")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_WORD = re.compile(r"[A-Za-z0-9_]{4,}")
_CAPTION_BEFORE = 240
_CAPTION_NEAR = 80
_SUGGEST_LIMIT = 3
_MIN_CAPTION_SCORE = 2


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return ""


def drop_image_catalog_history(
    messages: list[BaseMessage],
    *,
    drop_any_img_mention: bool = False,
) -> list[BaseMessage]:
    """Drop prior answers that catalog img# ids without having viewed pixels.

    A long catalog (>= 5 mentions) is always dropped. When the current question
    needs pixels, also drop short answers that cite img# — those were almost
    always guessed from filenames / surrounding text and poison the next pick.
    """
    threshold = 1 if drop_any_img_mention else _CATALOG_IMG_MENTIONS
    kept: list[BaseMessage] = []
    dropped = 0
    for message in messages:
        if isinstance(message, AIMessage) and _message_text(message).count("img#") >= threshold:
            dropped += 1
            continue
        kept.append(message)
    if dropped:
        logger.info("image_view dropped catalog history messages={}", dropped)
    return kept


def _last_user_question(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if not isinstance(message, HumanMessage):
            continue
        text = _message_text(message)
        if not text:
            continue
        for marker in _USER_QUESTION_MARKERS:
            if marker in text:
                return text.split(marker, 1)[-1]
        return text
    return ""


def question_needs_pixels(text: str) -> bool:
    return bool(_NEED_PIXELS.search(text or ""))


def _cjk_ngrams(text: str, size: int) -> set[str]:
    grams: set[str] = set()
    for run in _CJK_RUN.findall(text or ""):
        if len(run) < size:
            continue
        for index in range(len(run) - size + 1):
            grams.add(run[index : index + size])
    return grams


def _raw_caption_score(window: str, question: str) -> int:
    score = sum(1 for gram in _cjk_ngrams(question, 2) if gram in window)
    score += 4 * sum(1 for gram in _cjk_ngrams(question, 4) if gram in window)
    lowered = window.lower()
    score += 2 * sum(1 for word in _ASCII_WORD.findall(question or "") if word.lower() in lowered)
    return score


def _caption_score(window: str, question: str) -> int:
    near = window[-_CAPTION_NEAR:]
    far = window[:-_CAPTION_NEAR] if len(window) > _CAPTION_NEAR else ""
    return _raw_caption_score(near, question) * 3 + _raw_caption_score(far, question)


def suggest_image_ids(context: str, question: str, *, limit: int = _SUGGEST_LIMIT) -> list[str]:
    """Rank img# ids by how well the preceding caption matches the user question."""
    if not context or not question:
        return []
    four_grams = _cjk_ngrams(question, 4)
    ranked: list[tuple[int, int, str]] = []
    for match in _ANCHOR_RE.finditer(context):
        start = max(0, match.start() - _CAPTION_BEFORE)
        window = context[start : match.start()]
        # 4-gram required when the question has one: "开户申请" must not match "销户申请".
        if four_grams and not any(gram in window for gram in four_grams):
            continue
        score = _caption_score(window, question)
        if score >= _MIN_CAPTION_SCORE:
            # Later images win ties: form screenshots sit after the section heading.
            ranked.append((-score, -match.start(), match.group(1)))
    seen: set[str] = set()
    out: list[str] = []
    for _, _, image_id in sorted(ranked):
        if image_id in seen:
            continue
        seen.add(image_id)
        out.append(image_id)
        if len(out) >= limit:
            break
    return out


def _image_pick_hint(messages: list[BaseMessage]) -> str:
    question = _last_user_question(messages)
    context = "\n".join(_message_text(message) for message in messages)
    suggested = suggest_image_ids(context, question)
    if not suggested:
        return ""
    logger.info("image_view suggested_ids={}", suggested)
    return "本题附近标题更匹配的图片：" + "、".join(suggested) + "。请优先查看这些编号，不要默认第一张。"


def append_image_view_rules(messages: list[BaseMessage]) -> list[BaseMessage]:
    out = list(messages)
    extra = IMAGE_VIEW_PROMPT_RULES
    hint = _image_pick_hint(out)
    if hint:
        extra = f"{extra}\n7. {hint}"
    for index, message in enumerate(out):
        if not isinstance(message, SystemMessage):
            continue
        content = message.content if isinstance(message.content, str) else ""
        if IMAGE_VIEW_PROMPT_RULES in content:
            if hint and hint not in content:
                out[index] = SystemMessage(content=f"{content}\n{hint}")
            return out
        out[index] = SystemMessage(content=f"{content}\n\n{extra}")
        return out
    return [SystemMessage(content=extra), *out]


def prepare_vision_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Drop guessed img# history, then inject view-image rules + pick hint."""
    needs_pixels = question_needs_pixels(_last_user_question(messages))
    return append_image_view_rules(drop_image_catalog_history(messages, drop_any_img_mention=needs_pixels))


def _suggested_ids_for(messages: list[BaseMessage]) -> list[str]:
    question = _last_user_question(messages)
    context = "\n".join(_message_text(message) for message in messages)
    return suggest_image_ids(context, question)


def _apply_suggested_ids(
    view_calls: list[dict],
    suggested: list[str],
    registry: ImageRegistry,
) -> list[dict]:
    """Replace the model's image_ids with caption-ranked ids when it ignored the hint."""
    valid = [image_id for image_id in suggested if registry.get(image_id)]
    if not valid or not view_calls:
        return view_calls

    model_ids: list[str] = []
    for call in view_calls:
        args = _normalize_view_image_args(call.get("args"))
        model_ids.extend(args.get("image_ids") or [])

    overlap = [image_id for image_id in valid if image_id in set(model_ids)]
    picked = (overlap or valid)[:MAX_IMAGES_PER_TURN]
    if picked == model_ids[:MAX_IMAGES_PER_TURN]:
        return view_calls

    logger.info("image_view override_ids from={} to={}", model_ids, picked)
    first = dict(view_calls[0])
    args = _normalize_view_image_args(first.get("args"))
    args["image_ids"] = picked
    first["args"] = args
    return [first]


_SYNTHETIC_CALL_ID = "view_image_forced"


def _synthetic_view_calls(suggested: list[str], registry: ImageRegistry) -> list[dict]:
    """Build a view_image call when the model ignored tool_choice and answered in text."""
    ids = [image_id for image_id in suggested if registry.get(image_id)][:MAX_IMAGES_PER_TURN]
    if not ids:
        return []
    return [
        {
            "name": TOOL_NAME,
            "args": {"image_ids": ids, "quality": "standard"},
            "id": _SYNTHETIC_CALL_ID,
            "type": "tool_call",
        }
    ]


def _ai_message_for_second_round(ai_message: AIMessage, view_calls: list[dict]) -> AIMessage:
    """Keep tool_calls, drop first-round prose so round 2 cannot echo a guessed answer."""
    tool_calls = [
        {
            "name": TOOL_NAME,
            "args": _normalize_view_image_args(call.get("args")),
            "id": call.get("id") or "view_image",
            "type": "tool_call",
        }
        for call in view_calls
    ]
    return AIMessage(
        content="",
        tool_calls=tool_calls,
        additional_kwargs=dict(ai_message.additional_kwargs or {}),
        id=getattr(ai_message, "id", None),
    )


def _collect_ai(chunks: list[Any]) -> AIMessage:
    """Merge streamed chunks so tool-call args are complete JSON, not empty {}."""
    if not chunks:
        return AIMessage(content="")

    chunk_acc: AIMessageChunk | None = None
    last_message: AIMessage | None = None
    for chunk in chunks:
        if isinstance(chunk, AIMessageChunk):
            chunk_acc = chunk if chunk_acc is None else chunk_acc + chunk
        elif isinstance(chunk, AIMessage):
            last_message = chunk

    if chunk_acc is not None:
        return AIMessage(
            content=chunk_acc.content,
            additional_kwargs=dict(chunk_acc.additional_kwargs or {}),
            tool_calls=list(chunk_acc.tool_calls or []),
            invalid_tool_calls=list(getattr(chunk_acc, "invalid_tool_calls", None) or []),
            id=getattr(chunk_acc, "id", None),
        )
    if last_message is not None:
        return last_message

    texts: list[str] = []
    tool_calls: list[dict] = []
    for chunk in chunks:
        content = getattr(chunk, "content", "") or ""
        if isinstance(content, str):
            texts.append(content)
        tool_calls.extend(getattr(chunk, "tool_calls", None) or [])
    return AIMessage(content="".join(texts), tool_calls=tool_calls)


def _normalize_view_image_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    args = dict(raw)
    ids = args.get("image_ids")
    if ids is None:
        for key in ("image_id", "ids", "id"):
            if key in args:
                ids = args[key]
                break
    if isinstance(ids, str):
        ids = [part.strip() for part in ids.split(",") if part.strip()]
    elif ids is not None and not isinstance(ids, list):
        ids = [str(ids)]
    if ids is not None:
        args["image_ids"] = [str(item) for item in ids]
    args.setdefault("quality", "standard")
    return args


def _as_call_dict(call: Any) -> dict:
    if isinstance(call, dict):
        return call
    return {
        "name": getattr(call, "name", None),
        "args": getattr(call, "args", None) or {},
        "id": getattr(call, "id", None),
    }


def _view_calls(ai_message: AIMessage) -> list[dict]:
    calls: list[dict] = []
    for call in ai_message.tool_calls or []:
        item = _as_call_dict(call)
        if item.get("name") == TOOL_NAME:
            calls.append(item)
    if calls:
        return calls
    recovered: list[dict] = []
    for call in getattr(ai_message, "invalid_tool_calls", None) or []:
        item = _as_call_dict(call)
        if item.get("name") == TOOL_NAME:
            recovered.append(item)
    return recovered
