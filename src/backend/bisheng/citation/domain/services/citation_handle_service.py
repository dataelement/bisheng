"""Short citation handles for the Linsight task mode (F069 P1).

The model never sees a registry key such as ``knowledgesearch_0a3e7f35:0``.
Every retrieval hit is assigned a session-scoped handle (``S1``, ``S2`` …),
the model cites with ``[S3]`` / ``[S3][S7]`` / ``[S3, S7]``, and the workspace
write boundary converts those back into the private-use citation markers the
rest of the platform already understands. Everything downstream (preview,
resolve, persistence, export stripping) stays untouched.

The handle table lives in one Redis HASH per conversation
(``linsight:cite_handles:<session_id>``), so follow-up turns keep their
numbering. Allocation uses single-field atomic commands (``HINCRBY`` for the
counter, ``HSETNX`` to claim an identity) instead of a lock: the run lock is
per session-version, not per session, so two versions of one conversation may
run at once. A lost ``HSETNX`` race simply reads back the winner's number; the
skipped number stays unused, which the model never notices (the source table
lists the handles that exist).

Only handles the model actually wrote are converted. ``[3]``, ``[^3]``, link
labels, code spans and ``[S3]:`` definition lines are left alone and counted —
mapping a model-invented numbering onto our table would silently attach the
wrong source (design decision 2).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from bisheng.core.cache.redis_manager import get_redis_client

HANDLE_RULES_HEADER = "# 来源编号"
HANDLE_KEY_PREFIX = "linsight:cite_handles:"
HANDLE_TTL_SECONDS = 30 * 24 * 3600  # aligned with the citation runtime cache
HANDLE_PREFIX = "S"

_CITATION_START = ""
_CITATION_SEP = ""
_CITATION_END = ""

_HANDLE = r"S\d{1,4}"
_GROUP = rf"\[\s*{_HANDLE}(?:\s*[,，、]\s*{_HANDLE})*\s*\]"
# One or more adjacent groups (``[S3][S7]``); never the label of a markdown
# link (``[S3](url)``) and never glued to a word or another bracket.
# ASCII-only lookbehind: Python's \w matches CJK, and a handle glued to a
# Chinese word (``结论[S3]``) is the common case, not an identifier.
_RUN_RE = re.compile(rf"(?<![A-Za-z0-9_\[]){_GROUP}(?:\s*{_GROUP})*(?!\s*\()")
_HANDLE_RE = re.compile(_HANDLE)
# ``[S3]: 知识库·规则`` — a definition line the model wrote on its own; not a
# citation, only counted.
_DEF_LINE_RE = re.compile(rf"^[ \t]*{_GROUP}[ \t]*[:：]", re.M)
# Fenced blocks and inline code are never rewritten.
_CODE_RE = re.compile(r"(```.*?```|~~~.*?~~~|`[^`\n]*`)", re.S)


@dataclass
class ConvertResult:
    text: str
    converted: int = 0
    unknown: list[str] = field(default_factory=list)
    skipped_definitions: int = 0


# --------------------------------------------------------------------------
# identity / entry helpers
# --------------------------------------------------------------------------
def _type_name(item: Any) -> str:
    type_value = getattr(item, "type", None)
    return str(getattr(type_value, "value", type_value) or "")


def _item_key(item: Any) -> str | None:
    key = getattr(item, "key", None)
    if key:
        return str(key)
    citation_id = getattr(item, "citationId", None)
    if not citation_id:
        return None
    item_id = getattr(item, "itemId", None)
    return f"{citation_id}:{item_id}" if item_id is not None else str(citation_id)


def item_identity(item: Any) -> str | None:
    """Stable identity across retrievals: same chunk / same page → same handle."""
    payload = getattr(item, "sourcePayload", None)
    type_name = _type_name(item)
    item_id = getattr(item, "itemId", None)
    if type_name == "web":
        from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService

        url = getattr(payload, "url", None) or ""
        normalized = CitationRegistryService.normalize_url(url) if url else ""
        return f"web:{normalized}" if normalized else None
    document_id = getattr(payload, "documentId", None)
    if document_id is None or item_id is None:
        return None
    return f"{type_name or 'rag'}:{document_id}:{item_id}"


def _item_location(item: Any) -> str:
    payload = getattr(item, "sourcePayload", None)
    item_id = getattr(item, "itemId", None)
    for sub in getattr(payload, "items", None) or []:
        if str(getattr(sub, "itemId", None)) == str(item_id):
            return _location_label(getattr(sub, "page", None), getattr(sub, "chunkIndex", None), getattr(sub, "bbox", None))
    return ""


def _has_layout_boxes(bbox: Any) -> bool:
    """Whether a chunk carries PDF layout boxes (``{"chunk_bboxes": [...]}``)."""
    if not bbox:
        return False
    try:
        parsed = json.loads(bbox) if isinstance(bbox, str) else bbox
    except (TypeError, ValueError):
        return False
    boxes = parsed.get("chunk_bboxes") if isinstance(parsed, dict) else None
    return isinstance(boxes, list) and len(boxes) > 0


def _location_label(page: Any, chunk_index: Any, bbox: Any = None) -> str:
    """``第 N 页`` when the chunk has a real page number, else ``第 N 段``.

    Two page conventions reach here. Chunks parsed with a layout (PDF, and
    office files converted to PDF) carry bboxes, and their page is the
    zero-based page index the bboxes use — the first page is ``0``. Chunks
    without a layout carry a one-based page (slides) or ``0`` for "not
    paginated" (docx / xlsx / md). The chunk index is zero-based too.
    """
    try:
        page_no = int(page) if page is not None else None
    except (TypeError, ValueError):
        page_no = None
    if page_no is not None:
        if _has_layout_boxes(bbox):
            if page_no >= 0:
                return f"第 {page_no + 1} 页"
        elif page_no > 0:
            return f"第 {page_no} 页"
    try:
        if chunk_index is not None and int(chunk_index) >= 0:
            return f"第 {int(chunk_index) + 1} 段"
    except (TypeError, ValueError):
        pass
    return ""


def build_entry(item: Any, handle: str) -> dict:
    payload = getattr(item, "sourcePayload", None)
    type_name = _type_name(item)
    if type_name == "web":
        title = getattr(payload, "title", None) or getattr(payload, "url", None) or ""
        loc = getattr(payload, "source", None) or ""
        url = str(getattr(payload, "url", None) or "").strip()
    else:
        title = getattr(payload, "documentName", None) or getattr(payload, "knowledgeName", None) or ""
        loc = _item_location(item)
        url = ""
    entry = {
        "handle": handle,
        "key": _item_key(item),
        "type": type_name,
        "title": str(title)[:80],
        "loc": str(loc)[:40],
    }
    if url:
        # Surface forms the model may paste (normalized registry URL, plus the
        # provider URL recorded later). Used only to place a marker next to a
        # URL the report already wrote — never to invent a citation.
        entry["url"] = url
        entry["urls"] = [url]
    return entry


def handle_redis_key(session_id: str) -> str:
    return f"{HANDLE_KEY_PREFIX}{session_id}"


# --------------------------------------------------------------------------
# allocation
# --------------------------------------------------------------------------
async def assign_handles(scope: Any, items: list[Any] | None) -> dict[str, str]:
    """Give every registry item a session handle; returns ``{item_key: handle}``.

    Redis is the allocator; ``scope`` mirrors the table in-process
    (``scope.handles`` handle→key, ``scope.key_to_handle``, ``scope.entries``).
    Any Redis failure returns an EMPTY mapping — never partial numbering. The
    task mode then keeps the raw-key contract for the batch (F069 AC-17); the
    daily chat shows no source id at all (F072 AC-17).
    """
    if not items or not getattr(scope, "enabled", True):
        return {}
    session_id = getattr(scope, "session_id", None)
    if not session_id:
        return {}
    name = handle_redis_key(session_id)
    result: dict[str, str] = {}
    try:
        redis_client = await get_redis_client()
        for item in items:
            key = _item_key(item)
            identity = item_identity(item)
            if not key:
                continue
            # already numbered in this process?
            known = scope.key_to_handle.get(key)
            if known:
                result[key] = known
                continue
            handle = None
            if identity:
                existing = await redis_client.ahget(name, f"id:{identity}")
                if existing:
                    handle = _decode(existing)
            if handle is None:
                number = await redis_client.ahincrby(name, "next", 1)
                if number == 1 and getattr(scope, "pins_contract", True):
                    # table just came into existence: pin the task-mode contract this
                    # session runs under. The daily chat (F072) shares the table but has
                    # no switch; it must not pin, or it would override the task-mode
                    # kill switch for this conversation.
                    await redis_client.ahsetnx(name, "meta:enabled", "1" if scope.enabled else "0")
                candidate = f"{HANDLE_PREFIX}{number}"
                if identity:
                    claimed = await redis_client.ahsetnx(name, f"id:{identity}", candidate)
                    if not claimed:
                        winner = await redis_client.ahget(name, f"id:{identity}")
                        candidate = _decode(winner) or candidate
                handle = candidate
            entry = build_entry(item, handle)
            await redis_client.ahset(
                name, key=f"h:{handle}", value=json.dumps(entry, ensure_ascii=False), expiration=HANDLE_TTL_SECONDS
            )
            scope.register_handle(handle, key, entry)
            result[key] = handle
        await redis_client.aexpire_key(name, HANDLE_TTL_SECONDS)
    except Exception:
        logger.opt(exception=True).warning(f"citation handle allocation failed session={session_id}; keeping raw keys")
        return {}
    return result


def _decode(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value) or None


async def load_handle_table(session_id: str) -> tuple[dict[str, dict], bool | None]:
    """Read the whole table: ``({handle: entry}, meta_enabled)``; enabled is None when unset."""
    name = handle_redis_key(session_id)
    redis_client = await get_redis_client()
    raw = await redis_client.ahgetall(name) or {}
    entries: dict[str, dict] = {}
    enabled: bool | None = None
    for field_name, value in raw.items():
        field_name = _decode(field_name) or ""
        value = _decode(value) or ""
        if field_name.startswith("h:"):
            try:
                entry = json.loads(value)
            except (TypeError, ValueError):
                continue
            entries[field_name[2:]] = entry
        elif field_name == "meta:enabled":
            enabled = value == "1"
    return entries, enabled


# --------------------------------------------------------------------------
# tool-output rewriting (shared by the task mode and the daily chat)
# --------------------------------------------------------------------------
_CHUNK_ID_RE = re.compile(r"<chunk_id>(.*?)</chunk_id>", re.S)


def swap_chunk_id_for_handle(chunk: str, handles: dict[str, str]) -> str:
    """Show the model ``<ref>S3</ref>`` instead of ``<chunk_id>registry-key</chunk_id>``.

    ``format_retrieved_chunk`` is shared platform-wide and stays untouched; the
    swap happens on its output. Keys without a handle keep their tag.
    """

    def _repl(match: re.Match[str]) -> str:
        handle = handles.get(match.group(1).strip())
        return f"<ref>{handle}</ref>" if handle else match.group(0)

    return _CHUNK_ID_RE.sub(_repl, chunk)


def drop_chunk_ids(chunk: str) -> str:
    """Remove the registry key from a formatted chunk (no handle available)."""
    return _CHUNK_ID_RE.sub("", chunk)


def rewrite_web_results_with_handles(annotated: Any, handles: dict[str, str], entries: list[dict] | None = None) -> Any:
    """Show the model ``"ref": "S7"`` instead of the registry key on web results.

    ``annotated`` is the JSON string a web-search tool returns. Results without
    a handle keep their shape. ``entries`` (the task-mode scope mirror) records
    the URL the model saw, for the task mode's URL-marker pass.
    """
    if not handles or not isinstance(annotated, str):
        return annotated
    try:
        results = json.loads(annotated)
    except json.JSONDecodeError:
        return annotated
    if not isinstance(results, list):
        return annotated
    changed = False
    for result in results:
        if not isinstance(result, dict):
            continue
        key = str(result.get("citation_key") or "")
        handle = handles.get(key)
        if not handle:
            continue
        result["ref"] = handle
        if entries is not None:
            remember_web_surface_url(entries, key, str(result.get("url") or result.get("link") or ""))
        result.pop("citation_key", None)
        result.pop("itemId", None)
        changed = True
    return json.dumps(results, ensure_ascii=False) if changed else annotated


def drop_web_citation_keys(annotated: Any) -> Any:
    """Remove registry keys from web results (no handle available)."""
    if not isinstance(annotated, str):
        return annotated
    try:
        results = json.loads(annotated)
    except json.JSONDecodeError:
        return annotated
    if not isinstance(results, list):
        return annotated
    for result in results:
        if isinstance(result, dict):
            result.pop("citation_key", None)
            result.pop("itemId", None)
    return json.dumps(results, ensure_ascii=False)


# --------------------------------------------------------------------------
# text conversion (write boundary / answer path)
# --------------------------------------------------------------------------
def _split_code(text: str) -> list[tuple[bool, str]]:
    """Split into (is_code, segment) so code is never rewritten."""
    parts: list[tuple[bool, str]] = []
    last = 0
    for match in _CODE_RE.finditer(text):
        if match.start() > last:
            parts.append((False, text[last : match.start()]))
        parts.append((True, match.group(0)))
        last = match.end()
    if last < len(text):
        parts.append((False, text[last:]))
    return parts


def _protect_definition_lines(segment: str) -> tuple[str, list[str], int]:
    """Swap ``[Sn]:`` definition lines for placeholders so the run regex skips them."""
    stash: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        stash.append(match.group(0))
        return f"\x00DEF{len(stash) - 1}\x00"

    swapped = _DEF_LINE_RE.sub(_stash, segment)
    return swapped, stash, len(stash)


def _restore_definition_lines(segment: str, stash: list[str]) -> str:
    for idx, original in enumerate(stash):
        segment = segment.replace(f"\x00DEF{idx}\x00", original)
    return segment


def convert_handles_to_markers(text: str, handles: dict[str, str] | None) -> ConvertResult:
    """Rewrite ``[S3]``-style runs into private-use citation markers.

    ``handles`` maps handle → registry key. Unknown handles stay literal (and
    are reported); a run with no known handle is left untouched. Idempotent:
    converted text carries no ``[Sn]`` any more.
    """
    if not text or "[" not in text:
        return ConvertResult(text=text or "")
    handles = handles or {}
    result = ConvertResult(text="")
    out: list[str] = []
    for is_code, segment in _split_code(text):
        if is_code:
            out.append(segment)
            continue
        segment, stash, skipped = _protect_definition_lines(segment)
        result.skipped_definitions += skipped

        def _replace(match: re.Match[str]) -> str:
            seen: list[str] = []
            for handle in _HANDLE_RE.findall(match.group(0)):
                if handle not in seen:
                    seen.append(handle)
            known = [h for h in seen if h in handles]
            unknown = [h for h in seen if h not in handles]
            for h in unknown:
                if h not in result.unknown:
                    result.unknown.append(h)
            if not known:
                return match.group(0)
            result.converted += 1
            marker = _CITATION_START + _CITATION_SEP.join(handles[h] for h in known) + _CITATION_END
            tail = "".join(f"[{h}]" for h in unknown)
            return marker + tail

        segment = _RUN_RE.sub(_replace, segment)
        out.append(_restore_definition_lines(segment, stash))
    result.text = "".join(out)
    return result


_URL_CONTINUATION = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~:/?#[]@!$&'*+,;=%")


def remember_web_surface_url(entries: list[dict] | None, key: str, surface_url: str) -> None:
    """Record a URL string the model actually saw for one web handle.

    The registry stores a normalized URL; the tool result often shows a
    slightly different one. Both have to match before a pasted link can
    become a marker.
    """
    surface_url = (surface_url or "").strip()
    if not entries or not key or len(surface_url) < 12:
        return
    for entry in entries:
        if entry.get("key") != key:
            continue
        urls = entry.setdefault("urls", [])
        normalized = str(entry.get("url") or "").strip()
        if normalized and normalized not in urls:
            urls.insert(0, normalized)
        if surface_url not in urls:
            urls.append(surface_url)
        return


def _find_bounded_url(segment: str, url: str) -> int:
    """Index of ``url`` that is not a prefix of a longer URL."""
    start = 0
    while True:
        idx = segment.find(url, start)
        if idx < 0:
            return -1
        end = idx + len(url)
        nxt = segment[end] if end < len(segment) else ""
        if nxt and nxt in _URL_CONTINUATION:
            start = idx + 1
            continue
        return idx


def attach_web_url_markers(text: str, entries: list[dict] | None) -> str:
    """Put a citation marker after a web URL the report already contains.

    Only URLs registered for this run are marked, and only the first
    occurrence of each source. A source whose marker is already in the text
    is left alone. Code spans are not rewritten.
    """
    if not text or not entries:
        return text or ""
    candidates: list[tuple[str, str]] = []
    for entry in entries:
        if str(entry.get("type") or "") != "web":
            continue
        key = str(entry.get("key") or "")
        if not key or key in text:
            continue
        urls: list[str] = []
        for raw in [entry.get("url"), *(entry.get("urls") or [])]:
            url = str(raw or "").strip()
            if len(url) >= 12 and url not in urls:
                urls.append(url)
        for url in urls:
            candidates.append((url, key))
    if not candidates:
        return text
    candidates.sort(key=lambda item: len(item[0]), reverse=True)
    used: set[str] = set()
    out: list[str] = []
    for is_code, segment in _split_code(text):
        if is_code:
            out.append(segment)
            continue
        for url, key in candidates:
            if key in used or key in segment:
                if key in segment:
                    used.add(key)
                continue
            idx = _find_bounded_url(segment, url)
            if idx < 0:
                continue
            end = idx + len(url)
            if end < len(segment) and segment[end] == ")" and segment[idx - 2 : idx] == "](":
                end += 1
            segment = segment[:end] + _CITATION_START + key + _CITATION_END + segment[end:]
            used.add(key)
        out.append(segment)
    return "".join(out)


def strip_citation_handles(text: str) -> str:
    """Drop every ``[Sn]`` run (exports must not leak unresolved handles)."""
    if not text or "[" not in text:
        return text or ""
    out: list[str] = []
    for is_code, segment in _split_code(text):
        if is_code:
            out.append(segment)
            continue
        segment, stash, _ = _protect_definition_lines(segment)
        segment = _RUN_RE.sub("", segment)
        out.append(_restore_definition_lines(segment, stash))
    return "".join(out)


def count_handle_runs(text: str) -> int:
    """How many ``[Sn]`` runs a text carries (nudge / audit helper)."""
    if not text or "[" not in text:
        return 0
    total = 0
    for is_code, segment in _split_code(text):
        if is_code:
            continue
        segment, _, _ = _protect_definition_lines(segment)
        total += len(_RUN_RE.findall(segment))
    return total


# --------------------------------------------------------------------------
# prompt rules (task-mode replacement for citation.yaml under the handle contract)
# --------------------------------------------------------------------------
_HANDLE_RULES_CACHE: dict[str, str] = {}


def load_handle_rules() -> str:
    """The short, commission-style rules for the [Sn] contract (citation_handles.yaml)."""
    if "rules" not in _HANDLE_RULES_CACHE:
        try:
            from bisheng.core.prompts.prompt_loader import PromptLoader

            prompt_obj = PromptLoader().render_prompt("citation_handles", "linsight_handle_rules")
            _HANDLE_RULES_CACHE["rules"] = str(prompt_obj.prompt).strip()
        except Exception as e:  # pragma: no cover - configuration error surfaced in the prompt itself
            _HANDLE_RULES_CACHE["rules"] = f"{HANDLE_RULES_HEADER}\n\nFailed to load citation_handles prompt rules: {e}"
    return _HANDLE_RULES_CACHE["rules"]


def prompt_has_handle_rules(prompt: str | None) -> bool:
    return bool(prompt) and HANDLE_RULES_HEADER in prompt


def ensure_handle_rules(prompt: str | None) -> str:
    """Append the [Sn] rules once (idempotent), mirroring ensure_citation_rules."""
    if prompt_has_handle_rules(prompt):
        return prompt or ""
    base = (prompt or "").rstrip()
    rules = load_handle_rules()
    return f"{base}\n\n{rules}" if base else rules


# --------------------------------------------------------------------------
# export baking (P2): hidden markers -> visible [n] + a references section
# --------------------------------------------------------------------------
_MARKER_SPAN_RE = re.compile(rf"{_CITATION_START}(.*?){_CITATION_END}", re.S)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
EXPORT_HEADING_ZH = "参考资料"
EXPORT_HEADING_EN = "References"


@dataclass
class ExportRenderResult:
    text: str
    numbered: int = 0  # distinct sources that received a number
    unresolved: list[str] = field(default_factory=list)  # marker keys with no resolved item


def export_heading_for(text: str) -> str:
    """参考资料 when the report is (partly) Chinese, References otherwise."""
    return EXPORT_HEADING_ZH if _CJK_RE.search(text or "") else EXPORT_HEADING_EN


def _payload_items(item: Any) -> list:
    return list(getattr(getattr(item, "sourcePayload", None), "items", None) or [])


def _export_identity(item: Any, item_id: str | None) -> str:
    payload = getattr(item, "sourcePayload", None)
    type_name = _type_name(item)
    if type_name == "web":
        from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService

        url = getattr(payload, "url", None) or ""
        return f"web:{CitationRegistryService.normalize_url(url) if url else getattr(item, 'citationId', '')}"
    if type_name == "article":
        return f"article:{getattr(item, 'citationId', '')}"
    document_id = getattr(payload, "documentId", None)
    base = document_id if document_id is not None else getattr(item, "citationId", "")
    return f"{type_name or 'rag'}:{base}:{item_id if item_id is not None else ''}"


def _export_location(item: Any, item_id: str | None) -> str:
    for sub in _payload_items(item):
        if str(getattr(sub, "itemId", None)) == str(item_id):
            return _location_label(getattr(sub, "page", None), getattr(sub, "chunkIndex", None), getattr(sub, "bbox", None))
    return ""


def _export_line(item: Any, item_id: str | None) -> str:
    payload = getattr(item, "sourcePayload", None)
    type_name = _type_name(item)
    parts: list[str]
    if type_name == "web":
        url = getattr(payload, "url", None) or ""
        title = getattr(payload, "title", None) or url
        parts = [title, getattr(payload, "source", None) or "", url if title != url else ""]
    elif type_name == "article":
        parts = [getattr(payload, "title", None) or "", getattr(payload, "sourceUrl", None) or ""]
    else:
        name = getattr(payload, "documentName", None) or getattr(payload, "knowledgeName", None) or ""
        parts = [
            f"《{name}》" if name else "",
            _export_location(item, item_id),
            getattr(payload, "knowledgeName", None) or "",
        ]
    return " · ".join(str(x).strip() for x in parts if x and str(x).strip())


def render_citations_for_export(
    text: str, resolved_items: list[Any] | None, *, heading: str | None = None
) -> ExportRenderResult:
    """Bake hidden citation markers into visible ``[n]`` plus a references section.

    ``resolved_items`` are the registry items the EXPORTER may see (already run
    through the permission-filtering resolve service). A marker key whose
    source is not among them is dropped — it neither gets a number nor a line,
    so the exporter learns nothing about it. Numbers follow first appearance;
    two keys pointing at the same source (same chunk / same page) share one
    number. Unregistered short handles (``[S99]``) are stripped as before. With
    nothing resolvable the result equals the old strip behaviour.
    """
    from bisheng.citation.domain.services.citation_prompt_helper import unescape_citation_markers

    result = ExportRenderResult(text=text or "")
    if not text:
        return result
    text = unescape_citation_markers(text)
    index: dict[str, Any] = {}
    for item in resolved_items or []:
        citation_id = getattr(item, "citationId", None)
        if citation_id:
            index.setdefault(str(citation_id), item)
    numbers: dict[str, int] = {}
    lines: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        ordered: list[int] = []
        for key in match.group(1).split(_CITATION_SEP):
            key = key.strip()
            if not key:
                continue
            citation_id, _, item_id = key.partition(":")
            item = index.get(citation_id)
            if item is None:
                if key not in result.unresolved:
                    result.unresolved.append(key)
                continue
            identity = _export_identity(item, item_id or None)
            number = numbers.get(identity)
            if number is None:
                number = len(numbers) + 1
                numbers[identity] = number
                lines.append(_export_line(item, item_id or None))
            if number not in ordered:
                ordered.append(number)
        return "".join(f"[{n}]" for n in ordered)

    out: list[str] = []
    for is_code, segment in _split_code(text):
        out.append(segment if is_code else _MARKER_SPAN_RE.sub(_replace, segment))
    baked = "".join(out)
    # a marker the model never closed, or stray marker chars: drop them like strip_citation_markers does
    from bisheng.citation.domain.services.citation_prompt_helper import strip_citation_markers

    baked = strip_citation_markers(baked)
    baked = strip_citation_handles(baked)
    result.numbered = len(numbers)
    if numbers:
        title = heading or export_heading_for(text)
        section = "\n".join(f"{i}. {line}" if line else f"{i}." for i, line in enumerate(lines, start=1))
        baked = f"{baked.rstrip()}\n\n## {title}\n\n{section}\n"
    result.text = baked
    return result
