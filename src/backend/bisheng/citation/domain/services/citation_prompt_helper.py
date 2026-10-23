import re
from collections import OrderedDict, defaultdict, deque
from collections.abc import Sequence
from typing import Any

from langchain_core.documents import Document
from loguru import logger

from bisheng.citation.domain.repositories.implementations.message_citation_repository_impl import (
    MessageCitationRepositoryImpl,
)
from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    TempCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
from bisheng.citation.domain.services.citation_runtime_cache_service import (
    CitationRuntimeCacheService,
)
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.core.prompts.prompt_loader import PromptLoader

CITATION_START_MARKER = "\ue200"
CITATION_SEPARATOR_MARKER = "\ue201"
CITATION_END_MARKER = "\ue202"
CITATION_KEY_PATTERN = re.compile(
    rf"{CITATION_START_MARKER}(.*?){CITATION_END_MARKER}",
    re.DOTALL,
)
# Models (and write_file JSON) often emit the six-character sequence \ue200
# instead of U+E200. Extra backslashes from JSON double-escaping are common.
_ESCAPED_CITATION_MARKER_RE = re.compile(r"\\{1,4}ue20([012])", re.IGNORECASE)


def unescape_citation_markers(text: str) -> str:
    """Turn literal ``\\ue200`` / ``\\ue201`` / ``\\ue202`` into real PUA chars."""
    if not text or "ue20" not in text.lower():
        return text
    mapping = {
        "0": CITATION_START_MARKER,
        "1": CITATION_SEPARATOR_MARKER,
        "2": CITATION_END_MARKER,
    }

    def _repl(match: re.Match[str]) -> str:
        return mapping[match.group(1)]

    return _ESCAPED_CITATION_MARKER_RE.sub(_repl, text)


# Shapes an export output has to lose. The wrapper chars are invisible in Word /
# PDF while the ids between them are plain ASCII, so a preview badge such as
# ``\ue200knowledgesearch_18f5868b:0\ue202`` would surface as a bare
# ``knowledgesearch_18f5868b:0`` in the deliverable.
# Registry-shaped ids only (``knowledgesearch_…:n`` / ``websearch_…:n``), so a
# stray start marker cannot take an unrelated ``a:b`` token such as a clock
# time with it.
_CITATION_KEY_TOKEN = (
    rf"(?:{re.escape(CitationRegistryService.RAG_PREFIX)}|{re.escape(CitationRegistryService.WEB_PREFIX)})"
    r"[A-Za-z0-9_.\-]+:[A-Za-z0-9_.\-]+"
)
# A start marker with no end marker before the end of its line (or the next
# start marker). Only the marker char and the id-like tokens glued to it go;
# the surrounding sentence stays.
_UNTERMINATED_CITATION_RE = re.compile(
    rf"{CITATION_START_MARKER}(?![^\n{CITATION_START_MARKER}]*{CITATION_END_MARKER})"
    rf"(?:[ \t]*{_CITATION_KEY_TOKEN}(?:[ \t]*{CITATION_SEPARATOR_MARKER}[ \t]*{_CITATION_KEY_TOKEN})*)?"
)
_STRAY_CITATION_MARKER_TABLE = str.maketrans(
    {CITATION_START_MARKER: "", CITATION_SEPARATOR_MARKER: "", CITATION_END_MARKER: ""}
)


def strip_citation_markers(text: str) -> str:
    """Remove every citation span — wrapper chars and source ids alike.

    For export and download outputs only (docx / pdf / zipped markdown). The
    stored ``.md`` keeps its markers because the in-app preview parses them
    into badges. Nothing but the spans is touched: surrounding whitespace and
    punctuation are left exactly as written.

    Three shapes reach an export: a well-formed ``\ue200id[\ue201id…]\ue202``
    span, its literal ``\\ue200`` text form (normalised through
    :func:`unescape_citation_markers` first), and a span the model never
    closed. The unterminated pass runs before the span pass so a dangling
    start marker cannot pair with the end marker of a later, well-formed span
    and swallow the prose between them. Whatever marker char is still standing
    afterwards is dropped, so no private-use char survives.
    """
    if not text:
        return text
    text = unescape_citation_markers(text)
    if not any(marker in text for marker in (CITATION_START_MARKER, CITATION_SEPARATOR_MARKER, CITATION_END_MARKER)):
        return text
    text = _UNTERMINATED_CITATION_RE.sub("", text)
    text = CITATION_KEY_PATTERN.sub("", text)
    return text.translate(_STRAY_CITATION_MARKER_TABLE)


class CitationRegistryCollector:
    """Collect citation registry items across copied tool instances."""

    def __init__(self) -> None:
        self.items: list[CitationRegistryItemSchema] = []

    def clear(self) -> None:
        self.items.clear()

    def extend(self, items: list[CitationRegistryItemSchema]) -> None:
        self.items.extend(items)

    def list_items(self) -> list[CitationRegistryItemSchema]:
        return list(self.items)


def _load_citation_prompt_rules() -> str:
    try:
        prompt_loader = PromptLoader()
        prompt_obj = prompt_loader.render_prompt("citation", "citation_rules")
        return str(prompt_obj.prompt).strip()
    except Exception as e:
        return (
            f"Failed to load citation prompt rules: {e}. "
            "Please ensure the prompt file 'citation_rules' exists in the 'citation' category and is properly formatted."
        )


CITATION_PROMPT_RULES = _load_citation_prompt_rules()
_citation_runtime_cache_service = CitationRuntimeCacheService()


def prompt_has_citation_rules(prompt: str | None) -> bool:
    """True when a prompt already teaches citation-marker output, i.e. it contains the
    private-area start marker (actual U+E200 char or its literal ``\\ue200`` text).

    Used to gate the citation-rule backstop across entry points: inject the rules only
    when the user-visible prompt lacks them, so they are never duplicated when the
    prompt (default template or user-edited) already carries them.
    """
    if not prompt:
        return False
    return chr(0xE200) in prompt or (chr(92) + "ue200") in prompt


def ensure_citation_rules(prompt: str | None) -> str:
    """Return ``prompt`` with the citation rules appended unless it already teaches them.

    The single backstop shared by every chat entry point (daily chat, knowledge
    space, channel, linsight). Idempotent: a prompt carrying the start marker —
    the real U+E200 char or its literal ``\\ue200`` text — is returned unchanged,
    so a default template that already spells the rules is never duplicated.
    Callers apply their own ``format`` / ``replace`` BEFORE calling this: the
    rules text is appended verbatim and takes no placeholders.
    """
    if prompt_has_citation_rules(prompt):
        return prompt or ""
    base = (prompt or "").rstrip()
    return f"{base}\n\n{CITATION_PROMPT_RULES}" if base else CITATION_PROMPT_RULES


def _rag_registry_signature(item: CitationRegistryItemSchema) -> tuple[Any, ...]:
    payload = item.sourcePayload
    chunk_item = payload.items[0] if payload.items else None
    return (
        payload.documentId,
        chunk_item.chunkId if chunk_item else None,
        chunk_item.chunkIndex if chunk_item else None,
        chunk_item.content if chunk_item else payload.snippet,
    )


def _rag_document_signature(document: Document) -> tuple[Any, ...]:
    metadata = CitationRegistryService._parse_metadata(document)
    chunk_item = CitationRegistryService._build_rag_chunk_item(document)
    document_id = CitationRegistryService._parse_optional_int(metadata.get("document_id") or metadata.get("file_id"))
    return (
        document_id,
        chunk_item.chunkId,
        chunk_item.chunkIndex,
        chunk_item.content,
    )


def _build_rag_key_map(
    documents: list[Document],
    registry_items: list[CitationRegistryItemSchema],
) -> dict[int, str]:
    key_map: dict[int, str] = {}
    registry_by_signature: dict[tuple[Any, ...], deque[str]] = defaultdict(deque)
    fallback_keys = deque(item.key for item in registry_items if item.key)

    for item in registry_items:
        if item.key:
            registry_by_signature[_rag_registry_signature(item)].append(item.key)

    for index, document in enumerate(documents):
        signature = _rag_document_signature(document)
        if registry_by_signature[signature]:
            key_map[index] = registry_by_signature[signature].popleft()
        elif fallback_keys:
            key_map[index] = fallback_keys.popleft()
    return key_map


def _is_citable_rag_document(document: Document) -> bool:
    """Whether a retrieved document may be handed a citation key.

    A document with no metadata never could be. F054 adds a second refusal: a
    document carrying a document id that is not an integer. Workflow temp files
    are the case in point — the input node stores a random UUID as
    ``document_id`` and the workflow id as ``knowledge_id``, so the RAG payload
    (which types both as int) resolves neither, and the badge rendered but
    opened onto nothing. Only a *present and unparseable* id is refused; a
    document with no id at all keeps its previous treatment and falls back to
    metadata grouping, so the four live entry points are untouched.
    """
    metadata = document.metadata or {}
    if not metadata:
        return False
    raw_document_id = metadata.get("document_id") or metadata.get("file_id")
    if raw_document_id not in (None, "") and CitationRegistryService._parse_optional_int(raw_document_id) is None:
        return False
    return True


def _is_temp_file_document(document: Document) -> bool:
    """UUID document_id plus a non-integer knowledge_id (the workflow id).

    Must not fold these into RAG: the RAG payload types both ids as int and
    resolve would go looking for a knowledge_file row that does not exist.
    """
    metadata = document.metadata or {}
    if not metadata:
        return False
    raw_document_id = metadata.get("document_id") or metadata.get("file_id")
    if raw_document_id in (None, ""):
        return False
    if CitationRegistryService._parse_optional_int(raw_document_id) is not None:
        return False
    raw_knowledge_id = metadata.get("knowledge_id")
    if raw_knowledge_id not in (None, "") and CitationRegistryService._parse_optional_int(raw_knowledge_id) is not None:
        return False
    return True


def _temp_registry_signature(item: CitationRegistryItemSchema) -> tuple[Any, ...]:
    payload = item.sourcePayload
    chunk_item = payload.items[0] if payload.items else None
    return (
        payload.documentId,
        chunk_item.chunkId if chunk_item else None,
        chunk_item.chunkIndex if chunk_item else None,
        chunk_item.content if chunk_item else payload.snippet,
    )


def _temp_document_signature(document: Document) -> tuple[Any, ...]:
    metadata = CitationRegistryService._parse_metadata(document)
    chunk_item = CitationRegistryService._build_temp_chunk_item(document)
    document_id = CitationRegistryService._extract_temp_document_id(metadata)
    return (
        document_id,
        chunk_item.chunkId,
        chunk_item.chunkIndex,
        chunk_item.content,
    )


def _build_temp_key_map(
    documents: list[Document],
    registry_items: list[CitationRegistryItemSchema],
) -> dict[int, str]:
    key_map: dict[int, str] = {}
    registry_by_signature: dict[tuple[Any, ...], deque[str]] = defaultdict(deque)
    fallback_keys = deque(item.key for item in registry_items if item.key)

    for item in registry_items:
        if item.key:
            registry_by_signature[_temp_registry_signature(item)].append(item.key)

    for index, document in enumerate(documents):
        signature = _temp_document_signature(document)
        if registry_by_signature[signature]:
            key_map[index] = registry_by_signature[signature].popleft()
        elif fallback_keys:
            key_map[index] = fallback_keys.popleft()
    return key_map


def annotate_temp_documents_with_citations(documents: list[Document]) -> list[Document]:
    """Append tempsearch_ citation keys to temporary-knowledge-base documents."""
    if not documents:
        return documents
    try:
        indexed_citable_documents = [
            (index, document) for index, document in enumerate(documents) if _is_temp_file_document(document)
        ]
        citable_documents = [document for _, document in indexed_citable_documents]
        registry_items = CitationRegistryService.build_temp_registry(citable_documents)
        citable_key_map = _build_temp_key_map(citable_documents, registry_items)
        key_map = {
            original_index: citable_key_map[citable_index]
            for citable_index, (original_index, _) in enumerate(indexed_citable_documents)
            if citable_index in citable_key_map
        }
        annotated_documents: list[Document] = []
        for index, document in enumerate(documents):
            citation_key = key_map.get(index)
            metadata = dict(document.metadata or {})
            page_content = document.page_content or ""
            if citation_key:
                metadata["citation_key"] = citation_key
                page_content = f"{page_content}\n\ncitation_key: {citation_key}"
            annotated_documents.append(Document(page_content=page_content, metadata=metadata))
        return annotated_documents
    except Exception:
        # Citation failure must not abort answering (AC-23).
        logger.exception("failed to annotate temporary-knowledge-base citations; continuing without them")
        return documents


def annotate_rag_documents_with_citations(documents: list[Document]) -> list[Document]:
    """Append citation keys to RAG documents before prompt formatting."""
    if not documents:
        return documents

    indexed_citable_documents = [
        (index, document) for index, document in enumerate(documents) if _is_citable_rag_document(document)
    ]
    citable_documents = [document for _, document in indexed_citable_documents]
    registry_items = CitationRegistryService.build_rag_registry(citable_documents)
    citable_key_map = _build_rag_key_map(citable_documents, registry_items)
    key_map = {
        original_index: citable_key_map[citable_index]
        for citable_index, (original_index, _) in enumerate(indexed_citable_documents)
        if citable_index in citable_key_map
    }
    annotated_documents: list[Document] = []
    for index, document in enumerate(documents):
        citation_key = key_map.get(index)
        metadata = dict(document.metadata or {})
        page_content = document.page_content or ""
        if citation_key:
            metadata["citation_key"] = citation_key
            page_content = f"{page_content}\n\ncitation_key: {citation_key}"
        annotated_documents.append(Document(page_content=page_content, metadata=metadata))

    return annotated_documents


def annotate_web_results_with_citations(results: list[dict]) -> list[dict]:
    """Append citation keys to web search results before returning tool output."""
    if not results or not isinstance(results, list):
        return results

    registry_items = CitationRegistryService.build_web_registry(results)
    key_by_url_item_id = {
        (item.sourcePayload.url, item.itemId): item.key
        for item in registry_items
        if item.sourcePayload.url and item.itemId and item.key
    }

    annotated_results: list[dict] = []
    fallback_indexes_by_url: dict[str, int] = defaultdict(int)
    for result in results:
        annotated_result = dict(result)
        raw_url = CitationRegistryService._parse_optional_text(result.get("url") or result.get("link")) or ""
        normalized_url = CitationRegistryService.normalize_url(raw_url)
        item_index = fallback_indexes_by_url[normalized_url]
        item_id = CitationRegistryService.build_web_item_id(result, item_index)
        fallback_indexes_by_url[normalized_url] += 1
        citation_key = key_by_url_item_id.get((normalized_url, item_id))
        if citation_key:
            annotated_result["itemId"] = item_id
            annotated_result["citation_key"] = citation_key
        annotated_results.append(annotated_result)
    return annotated_results


def annotate_article_with_citation(
    article_doc_id: str,
    title: str | None = None,
    snippet: str | None = None,
    source_url: str | None = None,
    source_type: int | None = None,
) -> tuple[str, list[CitationRegistryItemSchema]]:
    """Register one channel article as a citation source.

    Returns the citation key the model must copy verbatim and the registry
    items to cache. Mirrors the RAG/web annotate helpers, minus the chunking:
    channel QA reads the article whole, so one article is one source.
    """
    items = CitationRegistryService.build_article_registry(
        article_doc_id=article_doc_id,
        title=title,
        snippet=snippet,
        source_url=source_url,
        source_type=source_type,
    )
    return items[0].key or "", items


def _split_citation_key(citation_key: Any) -> tuple[str | None, str | None]:
    if not isinstance(citation_key, str):
        return None, None
    if ":" not in citation_key:
        return None, None
    citation_id, item_id = citation_key.split(":", 1)
    if not citation_id or not item_id:
        return None, None
    return citation_id, item_id


def _clean_document_for_citation(document: Document) -> Document:
    metadata = dict(document.metadata or {})
    citation_key = metadata.pop("citation_key", None)
    page_content = document.page_content or ""
    if citation_key:
        page_content = page_content.replace(f"\n\ncitation_key: {citation_key}", "")
    return Document(page_content=page_content, metadata=metadata)


def collect_rag_citation_registry_items(documents: list[Document]) -> list[CitationRegistryItemSchema]:
    """Collect persistence-ready citation items from annotated RAG documents."""
    if not documents:
        return []

    grouped_documents: OrderedDict[str, list[Document]] = OrderedDict()
    # F041: capture access_scope from the ORIGINAL doc metadata before cleaning
    # ('shared' for toggle-OFF knowledge-space sources, else 'per_user').
    access_scope_by_citation: dict[str, str] = {}
    for document in documents:
        citation_id, _ = _split_citation_key((document.metadata or {}).get("citation_key"))
        if not citation_id:
            continue
        access_scope_by_citation.setdefault(citation_id, (document.metadata or {}).get("access_scope") or "per_user")
        grouped_documents.setdefault(citation_id, []).append(_clean_document_for_citation(document))

    registry_items: list[CitationRegistryItemSchema] = []
    knowledge_names = CitationRegistryService._load_knowledge_names(
        [document for grouped_docs in grouped_documents.values() for document in grouped_docs]
    )
    for citation_id, grouped_docs in grouped_documents.items():
        payload = CitationRegistryService._build_rag_payload_with_knowledge_names(grouped_docs, knowledge_names)
        registry_items.extend(
            CitationRegistryService._flatten_rag_payload(
                citation_id, payload, access_scope=access_scope_by_citation.get(citation_id, "per_user")
            )
        )
    return registry_items


def collect_temp_citation_registry_items(documents: list[Document]) -> list[CitationRegistryItemSchema]:
    """Collect persistence-ready citation items from annotated temp documents."""
    if not documents:
        return []
    try:
        grouped_documents: OrderedDict[str, list[Document]] = OrderedDict()
        for document in documents:
            citation_id, _ = _split_citation_key((document.metadata or {}).get("citation_key"))
            if not citation_id:
                continue
            grouped_documents.setdefault(citation_id, []).append(_clean_document_for_citation(document))

        registry_items: list[CitationRegistryItemSchema] = []
        for citation_id, grouped_docs in grouped_documents.items():
            payload = CitationRegistryService._build_temp_payload(grouped_docs)
            registry_items.extend(CitationRegistryService._flatten_temp_payload(citation_id, payload))
        return registry_items
    except Exception:
        logger.exception("failed to collect temporary-knowledge-base citations; continuing without them")
        return []


def collect_web_citation_registry_items(results: list[dict]) -> list[CitationRegistryItemSchema]:
    """Collect persistence-ready citation items from annotated web search results."""
    if not results or not isinstance(results, list):
        return []

    grouped_results: OrderedDict[str, list[dict]] = OrderedDict()
    for result in results:
        if not isinstance(result, dict):
            continue
        citation_id, _ = _split_citation_key(result.get("citation_key"))
        if not citation_id:
            continue
        result_without_citation = dict(result)
        result_without_citation.pop("citation_key", None)
        grouped_results.setdefault(citation_id, []).append(result_without_citation)

    registry_items: list[CitationRegistryItemSchema] = []
    for citation_id, grouped_page_results in grouped_results.items():
        first_result = grouped_page_results[0]
        raw_url = (
            CitationRegistryService._parse_optional_text(first_result.get("url") or first_result.get("link")) or ""
        )
        normalized_url = CitationRegistryService.normalize_url(raw_url)
        payload = CitationRegistryService._build_web_payload(normalized_url, grouped_page_results)
        registry_items.extend(CitationRegistryService._flatten_web_payload(citation_id, payload))
    return registry_items


def extract_citation_ids_from_text(text: str) -> set[str]:
    """Extract citation IDs that are actually referenced in generated text."""
    if not text:
        return set()

    text = unescape_citation_markers(text)
    citation_ids: set[str] = set()
    for marker_content in CITATION_KEY_PATTERN.findall(text):
        for citation_key in marker_content.split(CITATION_SEPARATOR_MARKER):
            citation_id, _ = _split_citation_key(citation_key.strip())
            if citation_id:
                citation_ids.add(citation_id)
    return citation_ids


def filter_registry_items_by_text(
    items: list[CitationRegistryItemSchema],
    text: str,
) -> list[CitationRegistryItemSchema]:
    """Keep only registry items referenced by the generated answer."""
    citation_ids = extract_citation_ids_from_text(text)
    if not citation_ids:
        return []
    return [item for item in items if item.citationId in citation_ids]


def _fallback_citation_keys(items: list[CitationRegistryItemSchema]) -> list[str]:
    """One ``citationId:itemId`` key per unique registered source, in first-seen order."""
    keys: list[str] = []
    seen: set[str] = set()
    for item in items:
        citation_id = item.citationId
        if not citation_id or citation_id in seen:
            continue
        seen.add(citation_id)
        key = _item_citation_key(item)
        if key:
            keys.append(key)
    return keys


def _item_citation_key(item: CitationRegistryItemSchema) -> str | None:
    if item.key and ":" in item.key:
        return item.key
    if not item.citationId:
        return None
    return f"{item.citationId}:{item.itemId or '0'}"


def _registry_item_text(item: CitationRegistryItemSchema) -> str:
    payload = item.sourcePayload
    parts: list[str] = []
    for chunk in getattr(payload, "items", None) or []:
        parts.append(getattr(chunk, "content", None) or "")
        parts.append(getattr(chunk, "snippet", None) or "")
    parts.append(getattr(payload, "snippet", None) or "")
    return "\n".join(part for part in parts if part)


def _overlap_score(query: str, haystack: str) -> float:
    query_text = re.sub(r"\s+", "", query or "")
    haystack_text = re.sub(r"\s+", "", haystack or "")
    if not query_text or not haystack_text:
        return 0.0
    if query_text in haystack_text:
        return 10.0 + len(query_text)
    if len(query_text) < 2:
        return 1.0 if query_text in haystack_text else 0.0
    grams = {query_text[index : index + 2] for index in range(len(query_text) - 1)}
    return sum(1 for gram in grams if gram in haystack_text) / len(grams)


def _best_item_key(query: str, items: list[CitationRegistryItemSchema]) -> str | None:
    best_score = 0.0
    best_key: str | None = None
    for item in items:
        key = _item_citation_key(item)
        if not key:
            continue
        score = _overlap_score(query, _registry_item_text(item))
        if score > best_score:
            best_score = score
            best_key = key
    if best_key:
        return best_key
    fallback = _fallback_citation_keys(items)
    return fallback[0] if fallback else None


_NUMBERED_CLAIM_RE = re.compile(r"^[ \t]*(?:\d+[\.、\)]|[（(]\d+[）)]|[-*•])[ \t]+(\S.+?)\s*$")


def _numbered_claim_lines(text: str) -> list[str]:
    return [match.group(1).strip() for line in text.splitlines() if (match := _NUMBERED_CLAIM_RE.match(line))]


def _match_keys_for_claims(claims: list[str], items: list[CitationRegistryItemSchema]) -> list[str]:
    keys: list[str] = []
    used: set[str] = set()
    for claim in claims:
        ranked: list[tuple[float, str]] = []
        for item in items:
            key = _item_citation_key(item)
            if not key:
                continue
            score = _overlap_score(claim, _registry_item_text(item))
            if score > 0:
                ranked.append((score, key))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]))
        chosen = next((key for _, key in ranked if key not in used), None)
        if chosen is None and ranked:
            chosen = ranked[0][1]
        if chosen:
            used.add(chosen)
            keys.append(chosen)
    return keys


def _distribute_keys_to_numbered_claims(text: str, keys: list[str]) -> str:
    lines = text.splitlines(keepends=True)
    key_index = 0
    rewritten: list[str] = []
    for line in lines:
        newline = ""
        body = line
        if line.endswith("\r\n"):
            body, newline = line[:-2], "\r\n"
        elif line.endswith("\n"):
            body, newline = line[:-1], "\n"
        if key_index < len(keys) and _NUMBERED_CLAIM_RE.match(body):
            rewritten.append(f"{body}{CITATION_START_MARKER}{keys[key_index]}{CITATION_END_MARKER}{newline}")
            key_index += 1
            continue
        rewritten.append(line)
    return "".join(rewritten)


def build_citation_turn_constraint(items: list[CitationRegistryItemSchema]) -> str:
    """Remind the model to copy this turn's real keys, not the prompt example."""
    keys = [key for key in (_item_citation_key(item) for item in items) if key]
    if not keys:
        return ""
    sample = "、".join(keys[:6])
    return (
        "【本轮引用约束】参考文本每条的 <chunk_id> 才是合法来源 ID"
        f"（本轮例如 {sample}）。列出多条事实时，每条末尾单独复制对应 <chunk_id>，"
        "禁止照抄提示词里的示例 ID（例如 knowledgesearch_18f5868b:0），"
        "禁止只在全文末尾标一次。"
    )


def _text_cites_registered_id(text: str, known_ids: set[str]) -> bool:
    for match in CITATION_KEY_PATTERN.finditer(text):
        for raw_key in match.group(1).split(CITATION_SEPARATOR_MARKER):
            citation_id, _ = _split_citation_key(raw_key.strip())
            if citation_id and citation_id in known_ids:
                return True
    return False


def strip_unregistered_citation_markers(text: str, items: list[CitationRegistryItemSchema]) -> str:
    """Drop citation markers whose ids were never registered.

    The citation rules tell the model to copy a retrieval result's id verbatim
    and never invent one, but nothing enforced it: a model that emitted
    ``\ue200knowledgesearch_bixude.mp4:0\ue202`` — the file name substituted for
    the id — got that marker persisted and rendered like any real one. The
    reader then clicked a footnote whose detail endpoint 404s and read
    "溯源详情加载失败", which describes a hallucination as a system fault.

    A marker may carry several ids separated by ``CITATION_SEPARATOR_MARKER``;
    the known ones survive and the marker is rewritten around them. A marker
    left with nothing is removed unless the answer cited *no* registered id
    at all and this round's registry is non-empty: then the first such marker
    is rewritten onto the real registered keys. Models copy the prompt
    example ``knowledgesearch_18f5868b:0`` even after retrieving
    ``tempsearch_`` chunks; deleting that marker also deletes the superscript.

    Empty registry still strips (the 116 case: invented id, nothing to map to).
    Mixed answers that already cite a registered id keep dropping the rest.

    Returns the text unchanged when it holds no markers, so the common path
    costs one regex search.
    """
    text = unescape_citation_markers(text)
    if not text or CITATION_START_MARKER not in text:
        return text

    known_ids = {item.citationId for item in items if item.citationId}
    fallback_keys = _fallback_citation_keys(items)
    remap_allowed = bool(fallback_keys) and not _text_cites_registered_id(text, known_ids)
    remapped = False

    if remap_allowed:
        body = CITATION_KEY_PATTERN.sub("", text)
        claims = _numbered_claim_lines(body)
        claim_keys = _match_keys_for_claims(claims, items) if len(claims) >= 2 else []
        if len(claim_keys) >= 2:
            return _distribute_keys_to_numbered_claims(body, claim_keys)
        best_key = _best_item_key(body, items)
        if best_key:
            fallback_keys = [best_key]

    def _rewrite(match: "re.Match[str]") -> str:
        nonlocal remapped
        kept: list[str] = []
        for raw_key in match.group(1).split(CITATION_SEPARATOR_MARKER):
            key = raw_key.strip()
            citation_id, _ = _split_citation_key(key)
            if citation_id and citation_id in known_ids:
                kept.append(key)
        if kept:
            return f"{CITATION_START_MARKER}{CITATION_SEPARATOR_MARKER.join(kept)}{CITATION_END_MARKER}"
        if remap_allowed and not remapped:
            remapped = True
            return f"{CITATION_START_MARKER}{CITATION_SEPARATOR_MARKER.join(fallback_keys)}{CITATION_END_MARKER}"
        return ""

    return CITATION_KEY_PATTERN.sub(_rewrite, text)


def select_registry_items_for_persistence(
    items: list[CitationRegistryItemSchema],
    text: str,
) -> list[CitationRegistryItemSchema]:
    """Prefer answer-referenced citations, and keep generated citations when no marker exists."""
    if not items:
        return []

    citation_ids = extract_citation_ids_from_text(text)
    if not citation_ids:
        return items

    return [item for item in items if item.citationId in citation_ids]


async def cache_citation_registry_items(
    items: list[CitationRegistryItemSchema],
) -> list[CitationRegistryItemSchema]:
    if not items:
        return []
    grouped_items = CitationRegistryService._group_registry_items(items)
    return await _citation_runtime_cache_service.save_citations(grouped_items)


def cache_citation_registry_items_sync(
    items: list[CitationRegistryItemSchema],
) -> list[CitationRegistryItemSchema]:
    if not items:
        return []
    grouped_items = CitationRegistryService._group_registry_items(items)
    return _citation_runtime_cache_service.save_citations_sync(grouped_items)


def _match_temp_file(payload: TempCitationPayloadSchema, files: list[dict]) -> dict | None:
    name = (payload.documentName or "").strip()
    source = (payload.sourceUrl or "").strip()
    for file in files:
        if not isinstance(file, dict):
            continue
        fname = str(file.get("filename") or file.get("file_name") or "").strip()
        furl = str(file.get("filepath") or file.get("file_path") or file.get("file_url") or "").strip()
        if name and fname and name == fname:
            return file
        if source and furl and source == furl:
            return file
    return None


def attach_temp_object_names(
    items: list[CitationRegistryItemSchema],
    files: list[dict] | None,
    user_id: int | str,
) -> list[CitationRegistryItemSchema]:
    """Fill main-bucket objectName on cited temp items and refresh the runtime cache.

    Uncited files are not promoted. Promotion failure drops that citation so
    answering can continue (AC-23).
    """
    if not items:
        return items
    if not any(item.type == CitationType.TEMP for item in items):
        return items

    from bisheng.core.storage.chat_attachment import CHAT_OBJECT_PREFIX, promote_chat_attachments_sync

    kept: list[CitationRegistryItemSchema] = []
    file_rows = [file for file in (files or []) if isinstance(file, dict)]
    for item in items:
        if item.type != CitationType.TEMP:
            kept.append(item)
            continue
        try:
            payload = TempCitationPayloadSchema.model_validate(item.sourcePayload)
            matched = _match_temp_file(payload, file_rows)
            if not matched and payload.sourceUrl:
                # Canvas debug has no question-message files; still promote
                # the cited original from the retriever's sourceUrl.
                matched = {
                    "filename": payload.documentName or "",
                    "file_url": payload.sourceUrl,
                }
            object_name = payload.objectName
            if matched and matched.get("object_name"):
                object_name = matched["object_name"]
            elif matched:
                promoted = promote_chat_attachments_sync([matched], user_id)
                object_name = (promoted[0].get("object_name") if promoted else None) or matched.get("object_name")
            if object_name and str(object_name).startswith("workflow_temp/"):
                logger.warning("refusing workflow_temp object prefix for citation {}", item.citationId)
                object_name = None
            if object_name and not str(object_name).startswith(CHAT_OBJECT_PREFIX):
                logger.warning("temp citation {} objectName is not a chat attachment key", item.citationId)
                object_name = None
            if not object_name:
                logger.warning(
                    "dropping temp citation {} because the original file could not be promoted", item.citationId
                )
                continue
            payload = payload.model_copy(update={"objectName": object_name, "previewUrl": None, "downloadUrl": None})
            kept.append(item.model_copy(update={"sourcePayload": payload}))
        except Exception:
            logger.exception("failed to attach objectName for temp citation {}; dropping it", item.citationId)
    temp_ids = {item.citationId for item in kept if item.type == CitationType.TEMP}
    try:
        cache_citation_registry_items_sync(kept)
    except Exception:
        logger.exception("failed to refresh citation cache after attaching temp object names")
        kept = [item for item in kept if item.citationId not in temp_ids]
    return kept


def save_message_citations_sync(
    message_id: int | str | None,
    items: list[CitationRegistryItemSchema],
    chat_id: str | None = None,
    flow_id: str | None = None,
) -> None:
    """Persist citation registry items for a saved chat message."""
    if not message_id or not items:
        if items:
            cache_citation_registry_items_sync(items)
        return

    if not isinstance(message_id, int):
        cache_citation_registry_items_sync(items)
        return

    with get_sync_db_session() as session:
        repository = MessageCitationRepositoryImpl(session)
        service = CitationRegistryService(repository)
        service.save_citations_sync(
            message_id=message_id,
            items=items,
            chat_id=chat_id,
            flow_id=flow_id,
        )
    cache_citation_registry_items_sync(items)


_RAG_SIGNED_URL_KEYS = ("previewUrl", "downloadUrl", "sourceUrl")


def serialize_citation_items_for_page(
    items: Sequence[CitationRegistryItemSchema],
) -> list[dict[str, Any]]:
    """JSON payloads for ``output_result.citations`` / FINAL_RESULT.

    RAG signed URLs are stripped so the client still calls ``/citations/resolve``
    (INV-7). Document names and snippets stay so the result page can render
    badges immediately.
    """
    payloads: list[dict[str, Any]] = []
    for item in items:
        data = item.model_dump(mode="json")
        if data.get("type") in (CitationType.RAG.value, CitationType.TEMP.value):
            source_payload = data.get("sourcePayload")
            if isinstance(source_payload, dict):
                for key in _RAG_SIGNED_URL_KEYS:
                    source_payload.pop(key, None)
        payloads.append(data)
    return payloads


async def persist_linsight_report_citations(
    message_id: int | str | None,
    chat_id: str | None,
    report_texts: Sequence[str] | None = None,
) -> list[CitationRegistryItemSchema]:
    """Persist only citations actually referenced in a linsight report.

    Unlike ``select_registry_items_for_persistence`` this keeps ZERO items when
    the report contains no markers (AC-05). Always returns the filtered items
    so the completion path can attach them to the page payload even when the
    ChatMessage id is missing (save is skipped in that case). Callers should
    swallow exceptions so task completion cannot fail because of citation
    persistence.
    """
    joined = "\n\n".join(text for text in (report_texts or []) if text)
    citation_ids = extract_citation_ids_from_text(joined)
    if not citation_ids:
        return []
    items = await _citation_runtime_cache_service.get_citations_by_ids(list(citation_ids))
    items = filter_registry_items_by_text(items, joined)
    if not items:
        return []
    if message_id and isinstance(message_id, int):
        await save_message_citations(message_id=message_id, items=items, chat_id=chat_id)
    return items


async def save_message_citations(
    message_id: int | str | None,
    items: list[CitationRegistryItemSchema],
    chat_id: str | None = None,
    flow_id: str | None = None,
) -> None:
    """Persist citation registry items for a saved chat message asynchronously."""
    if not message_id or not items:
        if items:
            await cache_citation_registry_items(items)
        return

    if not isinstance(message_id, int):
        await cache_citation_registry_items(items)
        return

    async with get_async_db_session() as session:
        repository = MessageCitationRepositoryImpl(session)
        service = CitationRegistryService(repository)
        await service.save_citations(
            message_id=message_id,
            items=items,
            chat_id=chat_id,
            flow_id=flow_id,
        )
    await cache_citation_registry_items(items)
