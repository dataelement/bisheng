"""F028 — Workstation conversation export & import service.

Two public flows share one core pipeline:

    load_messages -> build_turns -> render_markdown
                                      |       |
                                      |       +-- export: render docx/pdf/txt + stream back
                                      +---------- import: write .md + KnowledgeSpaceService.add_file

This file implements the **取数 / turn 构建** half (F028 T008).
Rendering, image preprocessing, and the import flow land in later tasks.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import importlib.resources
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import pypandoc
from loguru import logger

from io import BytesIO

from fastapi import UploadFile

from bisheng.common.errcode.knowledge_space import (
    SpaceFileNameDuplicateError,
    SpaceFileSizeLimitError,
    SpaceFolderNotFoundError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.common.errcode.tenant_quota import TenantStorageQuotaExceededError
from bisheng.common.errcode.workstation import (
    ConversationExportRenderFailedError,
    ConversationImportFailedError,
    ConversationImportFolderNotFoundError,
    ConversationImportPermissionDeniedError,
    ConversationImportQuotaExceededError,
    ConversationImportSpaceNotFoundError,
    ConversationMessageBatchTooLargeError,
    ConversationMessageNotFoundError,
    ConversationMessageNotOwnedError,
)
from bisheng.core.cache.utils import save_uploaded_file
from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileSource, FileType, KnowledgeFileDao
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao
from bisheng.knowledge.rag.pipeline.loader.utils.libreoffice_converter import convert_docx_to_pdf
from bisheng.user.domain.services.auth import LoginUser
from bisheng.workstation.domain.schemas.conversation_export import (
    ImportMessagesToKnowledgeRequest,
    ImportMessagesToKnowledgeResponse,
)


# --- Constants -------------------------------------------------------------

# Defensive cap; the primary boundary is Pydantic Field(max_length=200) on the
# request DTO. Service-side check protects internal callers and direct tests.
_MAX_BATCH = 200

# RAG citation markers are private-use Unicode (see T002 探查):
#    <citation_payload>    (with  as separator)
# A single greedy-lazy regex strips the well-formed pairs; the translate()
# pass below scrubs any stray markers left over from streaming truncation.
_CITATION_PATTERN = re.compile('[\\s\\S]*?')
_LONE_MARKER_TABLE = str.maketrans({'': '', '': '', '': ''})


# Markdown image syntax: ![alt](url)
_IMAGE_PATTERN = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

# Fallback for bare citation keys (``knowledgesearch_<hex>:N`` /
# ``websearch_<hex>:N``) that survive when the surrounding private-use Unicode
# markers were lost — e.g. the answer was assembled from streamed chunks that
# split a marker pair, or the front-end rendered ``U+E200`` as the literal
# ``"200"`` glyph (PUA fallback). Stripped after the well-formed marker pass.
# Literal backslash-escape forms of the PUA citation markers — e.g. the
# 6-character string ```` (backslash + ``u`` + ``e200``) — which leak
# through any layer that JSON-encoded a marker character as text instead of
# preserving the raw code point. Word/PDF rendered this verbatim previously.
_LITERAL_PUA_ESCAPE_PATTERN = re.compile(r'\\u[eE]20[012]')


# Emoji / pictograph characters that the bundled docker fonts
# (``WenQuanYi Zen Hei`` + ``Liberation Sans``) do not cover. When a docx
# contains these and is opened in Word the missing glyphs render as tofu
# boxes; the LibreOffice docx→pdf hop inherits the same. We replace them
# with `●` before docx/pdf rendering — markdown and txt keep the originals.
_EMOJI_PATTERN = re.compile(
    '['
    '\U0001F300-\U0001FAFF'  # symbols, emoticons, pictographs, ext, transport
    '\U00002600-\U000027BF'  # misc symbols + dingbats (★ ✓ ✗ ❌ …)
    '\U00002B00-\U00002BFF'  # misc symbols & arrows (⭐ ▶ ◀ …)
    '\U00002300-\U000023FF'  # misc technical (⏰ ⌛ …)
    ']'
)

_BARE_CITATION_KEY_PATTERN = re.compile(
    r'(?:||)*[ \t]*'
    r'(?:knowledgesearch|websearch)_[0-9a-fA-F]+:\d+'
    r'[ \t]*(?:||)*'
)

# Subprocess timeouts (spec §10 non-functional)
_PANDOC_TIMEOUT_SECONDS = 15
_LIBREOFFICE_TIMEOUT_SECONDS = 30
_IMAGE_FETCH_TIMEOUT_SECONDS = 5
_IMAGE_FETCH_CONCURRENCY = 8

# Filename sanitization (Windows-strictest cross-OS standard, AC-10)
_FORBIDDEN_FILENAME_CHARS = set('<>:"/\\|?*')
_MAX_FILENAME_TITLE_LEN = 80
_FALLBACK_TITLE = '未命名会话'


# --- Intermediate representation -------------------------------------------


@dataclass
class ConversationTurn:
    """One (query, [answer, ...]) pair in the final document.

    Multiple answers per query happen when the user clicked "regenerate";
    PRD says all answers should be exported (AC-06).
    """

    user_name: str
    user_query: str
    sender_name: str
    answers: list[str] = field(default_factory=list)


# --- Service ---------------------------------------------------------------


class ConversationExportService:
    """Workstation conversation export / import service (F028)."""

    # ---- public entrypoints (filled in later tasks) ----
    # async export_messages(req, user) -> (filename, mimetype, bytes_io)   # T010
    # async import_messages_to_knowledge(req, user) -> ImportResponse       # T012

    # ----------------------------------------------------------------------
    # Load & validate
    # ----------------------------------------------------------------------

    @classmethod
    async def _load_and_validate_messages(
        cls,
        chat_id: str,
        message_ids: list[int],
        user_id: int,
    ) -> tuple[list[ChatMessage], MessageSession]:
        """Load messages + their session with anti-IDOR validation.

        Error mapping (spec AC-08, AC-25, AC-26, AC-27, AC-28):

        - batch > 200                 -> ConversationMessageBatchTooLargeError (12061)
        - session missing / cross-user -> ConversationMessageNotOwnedError    (12062)
        - empty result (cross-chat / cross-user filtered to zero) -> 12062
        - partial result (some ids missing) -> ConversationMessageNotFoundError (12060)
        """
        if len(message_ids) > _MAX_BATCH:
            raise ConversationMessageBatchTooLargeError()

        session = await MessageSessionDao.async_get_one(chat_id)
        if session is None or session.user_id != user_id:
            # Either the chat does not exist or belongs to someone else;
            # do not leak which one — both become NotOwned (12062).
            raise ConversationMessageNotOwnedError()

        messages = await ChatMessageDao.aget_messages_by_ids(
            message_ids=message_ids, user_id=user_id, chat_id=chat_id,
        )
        if not messages:
            # SQL filtered everything out: either all ids belong to another
            # chat (AC-28) or another user (AC-25/26). Same error code,
            # no information leak.
            raise ConversationMessageNotOwnedError()
        if len(messages) < len(message_ids):
            existing = {m.id for m in messages}
            missing = sorted(set(message_ids) - existing)
            raise ConversationMessageNotFoundError(
                msg=f'消息不存在或已删除: {missing}',
            )
        return messages, session

    # ----------------------------------------------------------------------
    # Build conversation turns (Markdown intermediate representation source)
    # ----------------------------------------------------------------------

    @classmethod
    def _build_turns(
        cls,
        messages: list[ChatMessage],
        session: MessageSession,
        user_name: str,
    ) -> list[ConversationTurn]:
        """Group messages into (query, [answers]) turns and normalize text.

        Pairing rules (spec §3 + AC-06):
        - Primary: ChatMessage.extra.parentMessageId points to the query.
        - Fallback (legacy data with no parentMessageId): assign each answer
          to the latest preceding query (id-based adjacency).
        - All multi-answer items under one query are preserved in id order
          so "regenerate" history shows up in chronological order.

        Per-message normalization (AC-09, AC-14, AC-15):
        - agent_answer JSON {msg, events}: take msg, drop thinking/tool_call,
          render non-text outputs as [交互组件:...] placeholders.
        - All text passes through citation marker stripping (T002 真实形态).

        Sender label resolution (spec §7.1):
        - flow_type == WORKSTATION (15)      -> ChatMessage.sender (model name)
        - flow_type in {ASSISTANT, WORKFLOW} -> MessageSession.flow_name
        """
        if not messages:
            return []

        sorted_msgs = sorted(messages, key=lambda m: m.id or 0)
        id_map: dict[int, ChatMessage] = {m.id: m for m in sorted_msgs if m.id is not None}

        queries = [m for m in sorted_msgs if cls._is_query(m)]

        # 1) Assign answers to queries by parentMessageId; collect unassigned.
        answers_by_parent: dict[int, list[ChatMessage]] = {}
        orphans: list[ChatMessage] = []
        for m in sorted_msgs:
            if cls._is_query(m):
                continue
            parent_id = cls._parse_parent_msg_id(m)
            if parent_id is not None and parent_id in id_map:
                answers_by_parent.setdefault(parent_id, []).append(m)
            else:
                orphans.append(m)

        # 2) Time-adjacency fallback for orphan answers (legacy data path).
        if orphans and queries:
            query_ids_asc = [q.id for q in queries]
            for ans in orphans:
                preceding = [qid for qid in query_ids_asc if qid is not None and qid < (ans.id or 0)]
                if preceding:
                    answers_by_parent.setdefault(preceding[-1], []).append(ans)
                # else: no preceding query at all → drop silently (edge case)

        is_daily = session.flow_type == FlowType.WORKSTATION.value
        turns: list[ConversationTurn] = []
        for q in queries:
            answer_msgs = sorted(answers_by_parent.get(q.id, []), key=lambda m: m.id or 0)

            if is_daily:
                # Daily mode: take the model name from the first answer's
                # sender field. Empty sender → fall back to flow_name to
                # avoid showing a bare colon.
                sender_name = (answer_msgs[0].sender if answer_msgs else '') or session.flow_name or ''
            else:
                sender_name = session.flow_name or ''

            answer_texts = [cls._extract_answer_text(a) for a in answer_msgs]
            answer_texts = [cls._strip_citations(t) for t in answer_texts]
            # Drop fully-empty answer blocks (e.g. agent_tool_call / agent_thinking
            # categories sneak in via parent linkage; we don't render them).
            answer_texts = [t for t in answer_texts if t]

            turns.append(
                ConversationTurn(
                    user_name=user_name,
                    user_query=cls._strip_citations(cls._extract_query_text(q)),
                    sender_name=sender_name,
                    answers=answer_texts,
                )
            )
        return turns

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------

    @staticmethod
    def _is_query(m: ChatMessage) -> bool:
        return (m.category or '').lower() == 'question'

    @staticmethod
    def _extract_query_text(m: ChatMessage) -> str:
        """Pull the user-facing text out of a ``question`` ChatMessage.

        The frontend wraps user input in different JSON envelopes depending on
        the chat surface, so the raw ``message`` column is rarely a plain
        string:

        - daily mode (workstation) : ``{"query": "<text>", "files": [...]}``
        - app chat / workflow      : ``{"data": {...}, "input": "<text>"}``
        - legacy / plain           : just the raw string

        Returns the unwrapped text. If the envelope shape is unknown but the
        row is valid JSON, we fall back to the raw string to avoid silently
        dropping content (better to render a JSON-y line than an empty turn).
        """
        raw = m.message or ''
        if not raw:
            return ''
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return raw
        if not isinstance(data, dict):
            return raw
        for key in ('query', 'input'):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return raw

    @staticmethod
    def _parse_parent_msg_id(m: ChatMessage) -> Optional[int]:
        raw = m.extra or ''
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        pid = data.get('parentMessageId')
        if pid is None:
            return None
        try:
            return int(pid)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _extract_answer_text(m: ChatMessage) -> str:
        """Pull the user-facing answer text out of a ChatMessage.

        Three category formats exist (T003 探查):
        - 'answer'      : message is plain markdown text
        - 'agent_answer': message is JSON dict {msg, events: [...]}
        - others ('agent_tool_call', 'agent_thinking', ...): drop entirely
        """
        cat = (m.category or '').lower()
        raw = m.message or ''

        if cat == 'answer':
            return raw

        if cat == 'agent_answer':
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                # Stored as raw text in older rows — best-effort: return raw.
                return raw
            if not isinstance(data, dict):
                return raw

            msg = data.get('msg') or ''
            events = data.get('events') or []

            # The v2.5 agent-native format may keep the final answer text only
            # in ``events`` (last item with type ``text``) and leave ``msg``
            # empty. Fall through to events to recover that case, and also
            # capture text from workflow OUTPUT nodes whose ``output_type``
            # is ``text``.
            text_chunks: list[str] = []
            placeholders: list[str] = []
            for e in events:
                if not isinstance(e, dict):
                    continue
                etype = (e.get('type') or '').lower()
                # Drop reasoning / tool interactions.
                if etype in {'thinking', 'tool_call', 'tool_result'}:
                    continue
                if etype == 'text':
                    content = e.get('content') or ''
                    if content:
                        text_chunks.append(content)
                    continue
                if etype == 'output':
                    output_kind = (e.get('output_type') or e.get('kind') or '').lower()
                    if output_kind == 'text':
                        content = (
                            e.get('content')
                            or (e.get('data') or {}).get('content')
                            or (e.get('data') or {}).get('text')
                            or ''
                        )
                        if isinstance(content, str) and content:
                            text_chunks.append(content)
                    elif output_kind:
                        placeholders.append(f'[交互组件：{output_kind}]')

            body = msg if msg.strip() else '\n\n'.join(text_chunks)
            if placeholders:
                body = (body or '').rstrip() + '\n\n' + '\n\n'.join(placeholders)
            return body

        # agent_tool_call / agent_thinking / unknown -> drop
        return ''

    @staticmethod
    def _strip_citations(text: str) -> str:
        """Remove all forms of RAG citation markers.

        Three layered passes:

        1. ``_CITATION_PATTERN``: matched well-formed ``U+E200 … U+E202`` pairs
           and removes the whole payload.
        2. ``_LONE_MARKER_TABLE``: scrubs any single PUA marker left by SSE
           truncation or chunk boundaries.
        3. ``_BARE_CITATION_KEY_PATTERN``: fallback that catches naked
           ``knowledgesearch_<hex>:N`` / ``websearch_<hex>:N`` keys whose
           surrounding markers were dropped earlier (the front-end has been
           observed to render ``U+E200`` as the literal ``"200"`` glyph, which
           our PUA passes can't reach).
        """
        if not text:
            return text
        text = _CITATION_PATTERN.sub('', text)
        text = text.translate(_LONE_MARKER_TABLE)
        text = _LITERAL_PUA_ESCAPE_PATTERN.sub('', text)
        return _BARE_CITATION_KEY_PATTERN.sub('', text)

    # ----------------------------------------------------------------------
    # Markdown intermediate representation (AD-03, AD-04)
    # ----------------------------------------------------------------------

    @classmethod
    def _render_markdown(cls, turns: list[ConversationTurn]) -> str:
        """Render turns to the unified Markdown intermediate representation.

        Layout per AD-04 (matches PRD sample):

            **<user>：**

            <query>

            ---

            **<sender>：**

            <answer 1>

            <answer 2>   (multi-answer; sender label not repeated)

        Between turns: blank line separation only — the horizontal rule sits
        inside one turn (between query and answers), never between turns.
        """
        lines: list[str] = []
        for turn in turns:
            lines.append(f'**{turn.user_name}：**')
            lines.append('')
            lines.append(turn.user_query)
            lines.append('')
            lines.append('---')
            lines.append('')
            lines.append(f'**{turn.sender_name}：**')
            lines.append('')
            for ans in turn.answers:
                lines.append(ans)
                lines.append('')
            # Extra blank line between turns
            lines.append('')
        return '\n'.join(lines).rstrip() + '\n'

    # ----------------------------------------------------------------------
    # Renderers (T010): docx / pdf / txt
    # ----------------------------------------------------------------------

    @classmethod
    def _get_template_path(cls) -> str:
        """Resolve the reference docx template path from packaged assets."""
        # ``importlib.resources.files(<pkg>)`` is the modern (Python 3.9+) API.
        # We keep the path resolution lazy because tests may monkeypatch it.
        from bisheng.workstation import assets as _assets_pkg

        return str(importlib.resources.files(_assets_pkg) / 'conversation_export_template.docx')

    @staticmethod
    def _replace_emoji_for_office(markdown: str) -> str:
        """Replace emoji / pictograph code points with the CJK bullet `●`.

        Office-side fonts shipped in the bisheng-backend Docker image
        (``WenQuanYi Zen Hei`` + ``Liberation Sans/Mono``) lack the
        supplementary-plane emoji ranges. Without substitution Word renders
        these as tofu boxes (often falling back to a Japanese face the
        front-end calls ``MS Gothic``) and the LibreOffice docx→pdf hop
        inherits the same artefact. ``●`` is present in every CJK font and
        keeps the "list item / highlight" visual cue.

        Applied only on the docx/pdf path; the markdown/txt renderers keep
        the originals so downstream renderers with full emoji fonts (e.g.
        a user-side Markdown viewer) still see the source text intact.
        """
        if not markdown:
            return markdown
        return _EMOJI_PATTERN.sub('●', markdown)

    @classmethod
    def _render_docx(cls, markdown: str) -> bytes:
        """Convert Markdown to docx bytes via pypandoc + reference template.

        pypandoc's binary-format output requires writing to a temp file (it
        cannot return bytes directly for docx). Temp dir is auto-cleaned.
        """
        markdown = cls._replace_emoji_for_office(markdown)
        template = cls._get_template_path()
        with tempfile.TemporaryDirectory(prefix='conv_export_docx_') as tmpdir:
            out_path = os.path.join(tmpdir, 'out.docx')
            try:
                # Use the GFM-flavored markdown reader with two extensions:
                #   - lists_without_preceding_blankline: model output rarely
                #     puts a blank line before a list; without this pandoc
                #     attaches the list to the previous paragraph and the
                #     resulting docx renders every list item on one line.
                #   - hard_line_breaks: preserve in-paragraph line breaks
                #     (common in agent-native streamed text) instead of
                #     collapsing them into spaces.
                pypandoc.convert_text(
                    markdown,
                    'docx',
                    format='markdown+lists_without_preceding_blankline+hard_line_breaks',
                    outputfile=out_path,
                    extra_args=['--reference-doc=' + template],
                )
            except (RuntimeError, OSError) as e:
                logger.exception('pypandoc convert_text(docx) failed')
                raise ConversationExportRenderFailedError(
                    msg=f'pandoc 转换失败: {e}',
                )
            return Path(out_path).read_bytes()

    # ----------------------------------------------------------------------
    # PDF rendering via headless Chromium (Playwright)
    # ----------------------------------------------------------------------
    #
    # Previously we rendered docx with pandoc then converted to PDF with
    # LibreOffice. That path was brittle: LibreOffice mangled pandoc-emitted
    # tables (cells collapsed into separate one-line paragraphs), lists, and
    # heading alignment. Even pre-rasterising the LibreOffice output didn't
    # help — the source PDF was already wrong.
    #
    # Chromium's print path is a battle-tested HTML-to-PDF engine: tables,
    # CSS, web fonts, page breaks are all reliable. We render Markdown to
    # HTML with python-markdown (extensions: tables, fenced code, definition
    # lists, code highlighting via inline styles) and hand the HTML to
    # Chromium via Playwright. Playwright + the matching chromium binary are
    # already part of the bisheng-backend image.

    _PDF_CSS = """
    @page { size: A4; margin: 2cm; }
    html { font-size: 11pt; }
    body {
        font-family: "WenQuanYi Zen Hei", "Noto Sans CJK SC",
                     "Liberation Sans", "DejaVu Sans", sans-serif;
        line-height: 1.65;
        color: #1f1f1f;
        margin: 0;
    }
    h1, h2, h3, h4 { font-weight: 700; line-height: 1.3; margin: 1.1em 0 0.4em; }
    h1 { font-size: 1.55em; }
    h2 { font-size: 1.30em; border-bottom: 1px solid #e0e0e0; padding-bottom: 0.2em; }
    h3 { font-size: 1.13em; }
    p  { margin: 0.45em 0; }
    ul, ol { padding-left: 1.5em; margin: 0.4em 0; }
    li { margin: 0.18em 0; }
    table { border-collapse: collapse; width: 100%; margin: 0.7em 0;
            font-size: 0.95em; }
    th, td { border: 1px solid #bbb; padding: 6px 9px;
             text-align: left; vertical-align: top; }
    th { background: #f3f3f3; font-weight: 600; }
    pre { background: #f6f6f6; padding: 9px 12px; border-radius: 4px;
          overflow-x: auto; }
    code { font-family: "Liberation Mono", "DejaVu Sans Mono", monospace;
           font-size: 0.92em; }
    pre code { background: none; padding: 0; }
    blockquote { border-left: 3px solid #bbb; padding: 0.05em 0.9em;
                 margin: 0.6em 0; color: #555; }
    hr { border: none; border-top: 1px solid #ddd; margin: 1em 0; }
    img { max-width: 100%; }
    a { color: #2962ff; text-decoration: none; }
    strong { font-weight: 600; }
    """

    @classmethod
    def _markdown_to_html(cls, markdown_text: str) -> str:
        """Render markdown to a standalone HTML document string."""
        # Local import: python-markdown isn't needed elsewhere in the service.
        import markdown as md_lib

        body = md_lib.markdown(
            markdown_text,
            extensions=['extra', 'tables', 'fenced_code', 'sane_lists', 'nl2br'],
            output_format='html5',
        )
        return (
            '<!DOCTYPE html>'
            '<html lang="zh-CN"><head><meta charset="utf-8">'
            f'<style>{cls._PDF_CSS}</style>'
            f'</head><body>{body}</body></html>'
        )

    @classmethod
    async def _render_pdf(cls, markdown: str) -> bytes:
        """Render Markdown → PDF via headless Chromium (Playwright).

        Chromium gets the rendering it does best: HTML+CSS. Tables, lists,
        page breaks and CJK fonts all behave correctly because we declare
        the same font stack the docker image guarantees.
        """
        # Local import — heavy startup, only needed on the PDF path.
        from playwright.async_api import async_playwright

        html = cls._markdown_to_html(markdown)
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    args=['--no-sandbox', '--disable-dev-shm-usage'],
                )
                try:
                    page = await browser.new_page()
                    # ``domcontentloaded`` is enough — we have no external
                    # network resources to wait for (pre-fetched images are
                    # embedded as data URLs by an earlier step).
                    await page.set_content(html, wait_until='domcontentloaded')
                    return await page.pdf(
                        format='A4',
                        margin={'top': '2cm', 'right': '2cm',
                                'bottom': '2cm', 'left': '2cm'},
                        print_background=True,
                    )
                finally:
                    await browser.close()
        except Exception as e:
            logger.exception('Chromium PDF rendering failed')
            raise ConversationExportRenderFailedError(msg=f'PDF 渲染失败: {e}')

    @classmethod
    def _render_txt(cls, markdown: str) -> bytes:
        """Render Markdown to a plain-text approximation (AC-13).

        Rules (kept intentionally simple — txt is the lowest-fidelity format):

        - ``![alt](url)`` → ``[图片：<alt or basename>]``
        - fenced code blocks: strip the ```` ``` ```` fence lines, content stays
        - inline ``` ` ```, ``**bold**``, ``*italic*``, ``__bold__``, ``_italic_`` markers stripped
        - heading ``#+`` prefixes stripped
        - horizontal rules ``---`` stripped
        - pipe tables: convert to tab-separated rows; drop the ``|---|`` align line
        """
        text = markdown

        def _img_sub(m: re.Match) -> str:
            alt = m.group(1).strip()
            url = m.group(2).strip()
            label = alt or os.path.basename(url) or 'image'
            return f'[图片：{label}]'

        text = _IMAGE_PATTERN.sub(_img_sub, text)
        text = re.sub(r'^```[^\n]*\n', '', text, flags=re.MULTILINE)
        text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'\1', text)
        text = re.sub(r'__([^_]+)__', r'\1', text)
        text = re.sub(r'(?<!_)_([^_]+)_(?!_)', r'\1', text)
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^---+\s*$\n?', '', text, flags=re.MULTILINE)

        out_lines: list[str] = []
        for line in text.split('\n'):
            stripped = line.strip()
            if stripped.startswith('|') and stripped.endswith('|'):
                # Skip Markdown table alignment row (|---|:--:|---|)
                if re.match(r'^\s*\|[\s\-:|]+\|\s*$', line):
                    continue
                cells = [c.strip() for c in stripped.strip('|').split('|')]
                out_lines.append('\t'.join(cells))
            else:
                out_lines.append(line)
        return '\n'.join(out_lines).encode('utf-8')

    # ----------------------------------------------------------------------
    # Image preprocessing (AD-06)
    # ----------------------------------------------------------------------

    @classmethod
    async def _preprocess_images(cls, markdown: str, temp_dir: str) -> str:
        """Pre-download all ``![](url)`` images to ``temp_dir`` and rewrite the
        Markdown to point at local ``file://`` paths.

        Why: pandoc itself can fetch http(s) images, but its error surface is
        opaque and uncontrolled. By preloading we get one place to handle:
        timeouts, MinIO/HTTPS/data: protocols, and per-image fallback (AC-29).

        Concurrency: at most ``_IMAGE_FETCH_CONCURRENCY`` parallel downloads
        through a single shared ``httpx.AsyncClient``.
        """
        matches = list(_IMAGE_PATTERN.finditer(markdown))
        if not matches:
            return markdown

        unique_urls = sorted({m.group(2) for m in matches})
        sem = asyncio.Semaphore(_IMAGE_FETCH_CONCURRENCY)

        async with httpx.AsyncClient(timeout=_IMAGE_FETCH_TIMEOUT_SECONDS) as client:
            async def _wrap(url: str):
                async with sem:
                    return await cls._fetch_image_bytes(url, client)

            results = await asyncio.gather(
                *(_wrap(u) for u in unique_urls), return_exceptions=True,
            )

        replacements: dict[str, Optional[str]] = {}
        for url, result in zip(unique_urls, results):
            if isinstance(result, BaseException):
                logger.warning('image fetch failed url={} reason={}', url, result)
                replacements[url] = None
                continue
            raw, ext = result
            digest = hashlib.md5(url.encode('utf-8')).hexdigest()[:12]
            local_path = Path(temp_dir) / f'img_{digest}.{ext}'
            local_path.write_bytes(raw)
            replacements[url] = local_path.as_uri()

        def _replace(m: re.Match) -> str:
            alt = m.group(1)
            url = m.group(2)
            local_uri = replacements.get(url)
            if local_uri:
                return f'![{alt}]({local_uri})'
            return f'[图片加载失败：{url}]'  # AC-29

        return _IMAGE_PATTERN.sub(_replace, markdown)

    @staticmethod
    async def _fetch_image_bytes(
        url: str, client: httpx.AsyncClient,
    ) -> tuple[bytes, str]:
        """Fetch image bytes + extension hint. Raises on failure.

        Three protocol families:

        - ``data:`` URLs: decoded in-process (no network).
        - ``http(s)://``: shared AsyncClient (caller's timeout governs).
        - everything else: raises ValueError → caller substitutes placeholder.

        MinIO internal URLs are HTTP, so they go through the same client. The
        bisheng backend network reaches both internal MinIO and external HTTPS
        endpoints; no protocol switching is required.
        """
        if url.startswith('data:'):
            try:
                header, payload = url.split(',', 1)
            except ValueError as e:
                raise ValueError(f'malformed data URL: {url[:60]}') from e
            ext = 'png'
            if 'jpeg' in header or 'jpg' in header:
                ext = 'jpg'
            elif 'gif' in header:
                ext = 'gif'
            elif 'webp' in header:
                ext = 'webp'
            elif 'svg' in header:
                ext = 'svg'
            try:
                raw = base64.b64decode(payload)
            except binascii.Error as e:
                raise ValueError('invalid base64 payload') from e
            return raw, ext

        if url.startswith(('http://', 'https://')):
            resp = await client.get(url)
            resp.raise_for_status()
            ext = _guess_ext_from_content_type(resp.headers.get('content-type', ''))
            return resp.content, ext

        raise ValueError(f'unsupported image URL scheme: {url[:40]}')

    # ----------------------------------------------------------------------
    # Filename (AC-10)
    # ----------------------------------------------------------------------

    @classmethod
    def _resolve_filename(
        cls,
        session: MessageSession,
        ext: str,
        now: Optional[datetime] = None,
    ) -> str:
        """Build the export filename: ``<title>_yyyyMMddHHmm.<ext>``.

        Sanitization (Windows-strictest cross-OS rules):
        - empty / 'New Chat' title → '未命名会话'
        - forbidden chars ``<>:"/\\|?*`` and ASCII control chars → ``_``
        - trailing dots / spaces stripped (Windows hard rule)
        - title truncated to 80 chars (post-sanitization), then re-stripped

        Timestamp local clock by default; tests inject ``now`` for determinism.
        """
        raw_title = (session.name or '').strip()
        if not raw_title or raw_title.lower() == 'new chat':
            title = _FALLBACK_TITLE
        else:
            cleaned = []
            for c in raw_title:
                if c in _FORBIDDEN_FILENAME_CHARS or ord(c) < 32:
                    cleaned.append('_')
                else:
                    cleaned.append(c)
            title = ''.join(cleaned).rstrip(' .')
            if not title:
                title = _FALLBACK_TITLE
            if len(title) > _MAX_FILENAME_TITLE_LEN:
                title = title[:_MAX_FILENAME_TITLE_LEN].rstrip(' .') or _FALLBACK_TITLE

        ts = (now or datetime.now()).strftime('%Y%m%d%H%M')
        return f'{title}_{ts}.{ext}'

    # ----------------------------------------------------------------------
    # Import to knowledge space (T012)
    # ----------------------------------------------------------------------

    @classmethod
    async def import_messages_to_knowledge(
        cls,
        req: ImportMessagesToKnowledgeRequest,
        user: LoginUser,
        space_service,  # KnowledgeSpaceService; untyped to avoid circular import
    ) -> ImportMessagesToKnowledgeResponse:
        """Generate a Markdown file from the selected messages and add it to
        the target knowledge space, reusing the existing upload pipeline.

        Sequence (AC-16 ~ AC-24):
        - Load + validate messages (12060/12061/12062)
        - Pre-check space exists (12065)
        - Pre-check folder exists if parent_id (12066)
        - Pre-check upload permission (12067) — early short-circuit before
          we burn MinIO write / parse worker cycles
        - Build Markdown content (same generator as export_messages)
        - Resolve a unique filename within the target layer (AC-19): scan
          siblings, append (N) suffix on collision
        - Save bytes via the existing ``save_uploaded_file`` helper
        - Delegate to ``space_service.add_file``; one retry on race-condition
          duplicate (spec §3)
        """
        messages, session = await cls._load_and_validate_messages(
            chat_id=req.chat_id, message_ids=req.message_ids, user_id=user.user_id,
        )

        # Pre-check: space exists & is the right resource type.
        space = await KnowledgeDao.aquery_by_id(req.knowledge_space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise ConversationImportSpaceNotFoundError()

        # Pre-check: folder exists & is a directory (when parent_id given).
        if req.parent_id is not None:
            folder = await KnowledgeFileDao.query_by_id(req.parent_id)
            if not folder or folder.file_type != FileType.DIR.value:
                raise ConversationImportFolderNotFoundError()

        # Pre-check: upload permission. We borrow add_file's internal helper so
        # the check is byte-identical to what add_file would do later.
        try:
            if req.parent_id is not None:
                await space_service._require_permission_id(
                    'folder', req.parent_id, 'upload_file',
                    space_id=req.knowledge_space_id,
                )
            else:
                await space_service._require_permission_id(
                    'knowledge_space', req.knowledge_space_id, 'upload_file',
                )
        except SpacePermissionDeniedError:
            raise ConversationImportPermissionDeniedError()

        # Build Markdown — same generator that powers export_messages.
        turns = cls._build_turns(messages, session, user_name=user.user_name or '')
        markdown = cls._render_markdown(turns)
        markdown_bytes = markdown.encode('utf-8')

        # Resolve a non-conflicting filename within the target layer.
        base_filename = cls._resolve_filename(session, 'md')
        target_filename = await cls._resolve_unique_filename(
            knowledge_id=req.knowledge_space_id,
            parent_id=req.parent_id,
            base_filename=base_filename,
        )
        dup_renamed = (target_filename != base_filename)

        responses = await cls._upload_and_add_file(
            space_service=space_service,
            markdown_bytes=markdown_bytes,
            knowledge_id=req.knowledge_space_id,
            parent_id=req.parent_id,
            target_filename=target_filename,
            base_filename=base_filename,
        )

        if not responses:
            raise ConversationImportFailedError(msg='add_file returned no results')

        first = responses[0]
        # Race-retry path may have changed the on-disk filename; reflect it.
        actual_filename = getattr(first, 'file_name', None) or target_filename
        return ImportMessagesToKnowledgeResponse(
            file_id=first.id,
            target_filename=actual_filename,
            dup_renamed=dup_renamed or actual_filename != base_filename,
        )

    @classmethod
    async def _upload_and_add_file(
        cls,
        *,
        space_service,
        markdown_bytes: bytes,
        knowledge_id: int,
        parent_id: Optional[int],
        target_filename: str,
        base_filename: str,
    ) -> list:
        """Save bytes to MinIO then call ``space_service.add_file``.

        Maps known upstream errors to F028 error codes:
        - SpaceFileNameDuplicateError → resolve again + retry once → 12069 if still conflicting
        - SpaceFileSizeLimitError / TenantStorageQuotaExceededError → 12068
        - SpacePermissionDeniedError → 12067 (defensive — preflight should catch it)
        - SpaceNotFoundError / SpaceFolderNotFoundError → 12066 (defensive)
        - Anything else → 12069
        """
        try:
            file_path = await cls._save_markdown_to_minio(markdown_bytes, target_filename)
            return await space_service.add_file(
                knowledge_id=knowledge_id,
                file_path=[file_path],
                parent_id=parent_id,
                file_source=FileSource.SPACE_UPLOAD,
            )
        except SpaceFileNameDuplicateError:
            # Race window between our dedup scan and add_file: another row
            # claimed the name. Re-scan, rename, retry once.
            target_filename = await cls._resolve_unique_filename(
                knowledge_id=knowledge_id,
                parent_id=parent_id,
                base_filename=base_filename,
            )
            try:
                file_path = await cls._save_markdown_to_minio(markdown_bytes, target_filename)
                return await space_service.add_file(
                    knowledge_id=knowledge_id,
                    file_path=[file_path],
                    parent_id=parent_id,
                    file_source=FileSource.SPACE_UPLOAD,
                )
            except SpaceFileNameDuplicateError as e:
                raise ConversationImportFailedError(
                    msg='文件名持续冲突，请稍后重试',
                ) from e
        except (SpaceFileSizeLimitError, TenantStorageQuotaExceededError) as e:
            raise ConversationImportQuotaExceededError(msg=str(e) or '知识空间配额已满') from e
        except SpacePermissionDeniedError as e:
            raise ConversationImportPermissionDeniedError() from e
        except (SpaceNotFoundError, SpaceFolderNotFoundError) as e:
            raise ConversationImportFolderNotFoundError() from e
        except (ConversationImportSpaceNotFoundError, ConversationImportFolderNotFoundError,
                ConversationImportPermissionDeniedError, ConversationImportQuotaExceededError,
                ConversationImportFailedError):
            raise
        except Exception as e:
            logger.exception('conversation import: add_file failed')
            raise ConversationImportFailedError(msg=f'导入失败: {e}') from e

    @staticmethod
    async def _save_markdown_to_minio(markdown_bytes: bytes, filename: str) -> str:
        """Wrap bytes in an UploadFile and route through the existing
        ``save_uploaded_file`` helper so the file lands on MinIO under the
        canonical 'bisheng' folder, identical to a real upload."""
        bio = BytesIO(markdown_bytes)
        upload = UploadFile(filename=filename, file=bio)
        try:
            return await save_uploaded_file(upload, 'bisheng', filename)
        finally:
            await upload.close()

    @classmethod
    async def _resolve_unique_filename(
        cls,
        knowledge_id: int,
        parent_id: Optional[int],
        base_filename: str,
    ) -> str:
        """Return a filename that does not collide with anything currently
        sitting in ``(knowledge_id, parent_id)``.

        Strategy (AC-19): scan the target layer (single-level, non-recursive),
        if ``base_filename`` is taken, append ``(1)``, ``(2)``, ... up to a
        sensible safety bound. The scan + add_file remains non-atomic by
        design — the import flow handles the race by retrying once with a
        fresh resolution.
        """
        stem, dot, ext = base_filename.rpartition('.')
        if not dot:
            stem, ext = base_filename, ''

        # Scan the target layer. page_size big enough to catch all siblings
        # for the realistic conversation-export workload (folders here are
        # typically < a few hundred files).
        children = await SpaceFileDao.async_list_children(
            knowledge_id=knowledge_id,
            parent_id=parent_id,
            page=1,
            page_size=1000,
        )
        existing = {c.file_name for c in children if getattr(c, 'file_name', None)}
        if base_filename not in existing:
            return base_filename

        for n in range(1, 1001):
            candidate = f'{stem}({n}).{ext}' if ext else f'{stem}({n})'
            if candidate not in existing:
                return candidate
        # Pathological: 1000+ same-name siblings. Bail loud rather than loop.
        raise ConversationImportFailedError(
            msg='同名文件过多，请稍后重试或更换会话标题',
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _guess_ext_from_content_type(ct: str) -> str:
    """Map an HTTP Content-Type to a sensible file extension."""
    ct = (ct or '').lower()
    if 'png' in ct:
        return 'png'
    if 'jpeg' in ct or 'jpg' in ct:
        return 'jpg'
    if 'gif' in ct:
        return 'gif'
    if 'webp' in ct:
        return 'webp'
    if 'svg' in ct:
        return 'svg'
    return 'bin'
