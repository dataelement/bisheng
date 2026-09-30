"""Short citation handles for the workbench daily chat (F072).

The daily chat reuses the F069 contract: retrieval hits carry a session handle
(``S3``), the model writes ``[S3]`` and the backend turns it back into the
private-use citation markers the frontend already renders. Two things differ
from the task mode and live here:

- **Streaming.** Daily chat badges appear while the answer streams, so handles
  are converted *before* each delta goes out (:class:`HandleStreamConverter`),
  not once at completion.
- **Prompt.** The daily chat has no deliverable files and no per-turn source
  table; it gets its own rule text, and the legacy "copy the id verbatim"
  section that tenants saved in their system prompt is swapped out at run time
  (:func:`replace_legacy_citation_rules`).

History replay maps stored markers back to handles (:func:`markers_to_handles`)
so the model never sees two citation formats side by side.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from loguru import logger

from bisheng.citation.domain.services.citation_handle_service import (
    HANDLE_RULES_HEADER,
    ConvertResult,
    _split_code,
    convert_handles_to_markers,
)
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_END_MARKER,
    CITATION_SEPARATOR_MARKER,
    CITATION_START_MARKER,
    strip_citation_markers,
    unescape_citation_markers,
)

# --------------------------------------------------------------------------
# streaming conversion
# --------------------------------------------------------------------------
# Hold at most this many chars of an undecided handle run / inline code span;
# past it the text is released literally so a stray "[" never stalls the answer.
STREAM_HOLD_LIMIT = 128
# A legacy marker carries one or more 30-char keys; give it more room.
STREAM_LEGACY_HOLD_LIMIT = 256

# A (possibly unfinished) sequence of handle groups at the end of the text:
# "[", "[S", "[S1", "[S12, S", "[S3] ", "[S3][S7". Fullmatch only.
_OPEN_RUN_TAIL_RE = re.compile(r"(?:\[\s*(?:S\d{0,4}(?:\s*[,，、]\s*(?:S\d{0,4})?)*)?\s*\]?\s*)+")
# The beginning of an escaped marker ("" written as six characters).
_ESCAPE_TAIL_RE = re.compile(r"\\{1,4}(?:u(?:e(?:2(?:0)?)?)?)?$", re.IGNORECASE)
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~)", re.M)
# Start / end of a legacy marker in either form (real char or escaped text).
_LEGACY_START_RE = re.compile(r"\ue200|\\{1,4}ue200", re.I)
_LEGACY_END_RE = re.compile(r"\ue202|\\{1,4}ue202", re.I)
# Placeholders for chars the converter has already released literally.
_RELEASED_BRACKET = "\x01"
_RELEASED_MARKER = "\x02"


def _split_code_streaming(text: str) -> list[tuple[bool, str]]:
    """Like ``_split_code`` but an unclosed fence runs to the end as code.

    While streaming, a fence that has opened but not closed yet is code — its
    content must not be converted and then "un-converted" once it closes.
    """
    fences = list(_FENCE_RE.finditer(text))
    if len(fences) % 2 == 1:
        start = fences[-1].start()
        return [*_split_code(text[:start]), (True, text[start:])]
    return _split_code(text)


def _convert_streaming(text: str, handles: dict[str, str]) -> ConvertResult:
    """Drop model-written legacy markers, then convert ``[Sn]`` runs."""
    result = ConvertResult(text="")
    out: list[str] = []
    for is_code, segment in _split_code_streaming(text):
        if is_code:
            out.append(segment)
            continue
        converted = convert_handles_to_markers(strip_citation_markers(segment), handles)
        result.converted += converted.converted
        result.skipped_definitions += converted.skipped_definitions
        for handle in converted.unknown:
            if handle not in result.unknown:
                result.unknown.append(handle)
        out.append(converted.text)
    result.text = "".join(out)
    return result


def count_legacy_markers(text: str) -> int:
    """Citation spans the model wrote itself (verbatim registry ids)."""
    if not text:
        return 0
    text = unescape_citation_markers(text)
    return text.count(CITATION_START_MARKER)


@dataclass
class StreamStats:
    converted: int = 0
    unknown: list[str] = field(default_factory=list)
    legacy_markers: int = 0


class HandleStreamConverter:
    """Convert ``[Sn]`` handles in a streamed answer before each delta goes out.

    ``feed`` returns the part that is safe to emit now; ``flush`` returns the
    rest at the end of a text run (a tool call, the end of the stream, an
    interruption). Only the tail that could still change meaning is held back:
    an unfinished handle run, a run whose continuation / link paren / definition
    colon is still undecided, an open legacy marker, an escape sequence that has
    not finished, an inline code span that has not closed.

    Invariant (pinned by tests): however the text is chunked, the concatenated
    output equals converting the whole text at once.
    """

    def __init__(self, handles: dict[str, str] | None = None):
        # handle -> registry key; the caller may keep mutating this dict as
        # tools allocate handles during the turn.
        self.handles = handles if handles is not None else {}
        self._raw = ""  # everything fed so far, with released chars swapped for placeholders
        self._committed = 0  # raw chars whose output is final
        # Output is rendered from ``_checkpoint`` on; text before it is frozen
        # in ``_frozen``. The checkpoint only moves if a render ever disagrees
        # with what was already emitted, so one surprise never stalls the answer.
        self._checkpoint = 0
        self._frozen = ""
        self._emitted_since = ""
        self.stats = StreamStats()

    # -- public ------------------------------------------------------------
    def feed(self, text: str) -> str:
        if not text:
            return ""
        self._raw += text
        return self._advance(self._safe_cut())

    def flush(self) -> str:
        out = self._advance(len(self._raw))
        final = _convert_streaming(self._raw, self.handles)
        self.stats.converted = final.converted
        self.stats.unknown = list(final.unknown)
        self.stats.legacy_markers = count_legacy_markers(self._raw.replace(_RELEASED_MARKER, CITATION_START_MARKER))
        return out

    @property
    def text(self) -> str:
        """Everything emitted so far."""
        return self._frozen + self._emitted_since

    # -- internals ---------------------------------------------------------
    def _render(self, raw: str) -> str:
        converted = _convert_streaming(raw, self.handles).text
        return converted.replace(_RELEASED_BRACKET, "[").replace(_RELEASED_MARKER, "")

    def _advance(self, cut: int) -> str:
        if cut <= self._committed:
            return ""
        rendered = self._render(self._raw[self._checkpoint : cut])
        if not rendered.startswith(self._emitted_since):
            # Should not happen (cut points are chosen so earlier output is
            # final). Never rewrite what the reader already has: freeze it and
            # render the rest on its own.
            logger.warning("daily citation stream: render diverged from emitted text; freezing at checkpoint")
            self._frozen += self._emitted_since
            self._emitted_since = ""
            self._checkpoint = self._committed
            rendered = self._render(self._raw[self._checkpoint : cut])
        self._committed = cut
        out = rendered[len(self._emitted_since) :]
        self._emitted_since = rendered
        return out

    def _safe_cut(self) -> int:
        raw = self._raw
        end = len(raw)
        cut = end
        # 1. an unfinished handle run at the end
        window_start = max(self._committed, end - STREAM_HOLD_LIMIT)
        for idx in range(window_start, end):
            if raw[idx] == "[" and _OPEN_RUN_TAIL_RE.fullmatch(raw, idx):
                cut = min(cut, idx)
                break
        else:
            # Longer than the hold limit: release the bracket literally.
            idx = raw.rfind("[", self._committed, window_start)
            if idx >= 0 and _OPEN_RUN_TAIL_RE.fullmatch(raw, idx):
                self._release(idx, _RELEASED_BRACKET)
        # 2. an open legacy marker (real or escaped)
        unescaped_tail_start = self._legacy_open_start()
        if unescaped_tail_start is not None:
            if end - unescaped_tail_start <= STREAM_LEGACY_HOLD_LIMIT:
                cut = min(cut, unescaped_tail_start)
            else:
                self._release(unescaped_tail_start, _RELEASED_MARKER)
        escape = _ESCAPE_TAIL_RE.search(raw, max(self._committed, end - 8))
        if escape:
            cut = min(cut, escape.start())
        # 3. an inline code span still open on the current line
        line_start = raw.rfind("\n", 0, end) + 1
        if not self._in_open_fence(raw):
            ticks = [m.start() for m in re.finditer(r"`", raw[line_start:])]
            if len(ticks) % 2 == 1:
                tick = line_start + ticks[-1]
                if end - tick <= STREAM_HOLD_LIMIT:
                    cut = min(cut, tick)
        return max(cut, self._committed)

    def _legacy_open_start(self) -> int | None:
        raw = self._raw
        starts = list(_LEGACY_START_RE.finditer(raw, self._committed))
        if not starts:
            return None
        start = starts[-1].start()
        if _LEGACY_END_RE.search(raw, start):
            return None
        return start

    @staticmethod
    def _in_open_fence(raw: str) -> bool:
        return len(_FENCE_RE.findall(raw)) % 2 == 1

    def _release(self, idx: int, placeholder: str) -> None:
        self._raw = self._raw[:idx] + placeholder + self._raw[idx + 1 :]


# --------------------------------------------------------------------------
# history replay
# --------------------------------------------------------------------------
_MARKER_SPAN_RE = re.compile(rf"{CITATION_START_MARKER}(.*?){CITATION_END_MARKER}", re.S)


def markers_to_handles(text: str, key_to_handle: dict[str, str] | None) -> str:
    """Rewrite stored citation markers as ``[Sn]`` for the model's history.

    Keys without a handle (answers from before the migration, an expired
    table) are dropped with their marker; the prose around them stays.
    """
    if not text:
        return text or ""
    text = unescape_citation_markers(text)
    if CITATION_START_MARKER not in text:
        return text
    key_to_handle = key_to_handle or {}

    def _replace(match: re.Match[str]) -> str:
        handles: list[str] = []
        for key in match.group(1).split(CITATION_SEPARATOR_MARKER):
            handle = key_to_handle.get(key.strip())
            if handle and handle not in handles:
                handles.append(handle)
        return "".join(f"[{h}]" for h in handles)

    text = _MARKER_SPAN_RE.sub(_replace, text)
    # anything left (an unterminated span) goes the export way
    return strip_citation_markers(text)


# --------------------------------------------------------------------------
# prompt rules
# --------------------------------------------------------------------------
_DAILY_RULES_CACHE: dict[str, str] = {}

# Top-level heading of the legacy section in the three shipped default templates.
_LEGACY_HEADING_RE = re.compile(r"^[ \t]*#[ \t]+(引用规则|Citation Rules|引用ルール)[ \t]*$", re.M | re.I)
# Its sub-sections; anything else under the heading (e.g. "## 其他信息" holding
# {cur_date}) is not part of the rules and must survive.
_LEGACY_SUBSECTIONS = {
    "来源 id",
    "来源id",
    "标记格式",
    "使用要求",
    "source id",
    "format",
    "requirements",
    "ソースid",
    "ソース id",
    "フォーマット",
    "要件",
}
_HEADING_RE = re.compile(r"^[ \t]*(#{1,6})[ \t]+(.+?)[ \t]*$", re.M)
# Signs of the legacy contract when the heading was edited away.
_LEGACY_HINT_RE = re.compile(r"<chunk_id>|citation_key|\\ue20[012]|[]", re.I)


def load_daily_handle_rules() -> str:
    if "rules" not in _DAILY_RULES_CACHE:
        try:
            from bisheng.core.prompts.prompt_loader import PromptLoader

            prompt_obj = PromptLoader().render_prompt("citation_handles", "daily_handle_rules")
            _DAILY_RULES_CACHE["rules"] = str(prompt_obj.prompt).strip()
        except Exception as e:  # pragma: no cover - configuration error surfaced in the prompt itself
            _DAILY_RULES_CACHE["rules"] = f"{HANDLE_RULES_HEADER}\n\nFailed to load daily handle rules: {e}"
    return _DAILY_RULES_CACHE["rules"]


def replace_legacy_citation_rules(prompt: str | None) -> str:
    """Swap the saved "copy the id verbatim" section for the handle rules.

    Only the legacy heading and its known sub-sections are replaced; other
    sub-sections under the same heading (the date line) are kept. Prompts that
    already carry the handle rules are returned unchanged. When the legacy
    wording is present but its heading was edited away, the handle rules are
    appended and win by their own "this section prevails" sentence.
    """
    prompt = prompt or ""
    if HANDLE_RULES_HEADER in prompt:
        return prompt
    rules = load_daily_handle_rules()
    match = _LEGACY_HEADING_RE.search(prompt)
    if match:
        start = match.start()
        end = len(prompt)
        for heading in _HEADING_RE.finditer(prompt, match.end()):
            level = len(heading.group(1))
            title = heading.group(2).strip().lower()
            if level == 1 or title not in _LEGACY_SUBSECTIONS:
                end = heading.start()
                break
        head = prompt[:start].rstrip()
        tail = prompt[end:].lstrip("\n")
        parts = [p for p in (head, rules, tail) if p]
        return "\n\n".join(parts)
    return ensure_daily_handle_rules(prompt)


def ensure_daily_handle_rules(prompt: str | None) -> str:
    """Append the daily rules once (idempotent on the shared header)."""
    prompt = prompt or ""
    if HANDLE_RULES_HEADER in prompt:
        return prompt
    base = prompt.rstrip()
    rules = load_daily_handle_rules()
    return f"{base}\n\n{rules}" if base else rules


def prompt_has_legacy_citation_wording(prompt: str | None) -> bool:
    return bool(prompt) and bool(_LEGACY_HINT_RE.search(prompt))
