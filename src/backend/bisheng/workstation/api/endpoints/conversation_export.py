"""F028 — Conversation export & import HTTP endpoints.

Two POST endpoints sit under ``/api/v1/chat/messages``:
- ``/export`` — synchronous file stream (docx/pdf/md/txt)
- ``/import-to-knowledge`` — synchronous JSON, fires Celery parse in background

Router prefix mounts at the API root rather than under ``/workstation`` so the
URL matches the PRD ("会话消息" 是 chat 的子资源), even though the
implementation lives in the workstation domain module.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.workstation import (
    ConversationExportFormatUnsupportedError,
    ConversationExportRenderFailedError,
)
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)
from bisheng.workstation.domain.schemas.conversation_export import (
    ExportFormat,
    ExportMessagesRequest,
    ImportMessagesToKnowledgeRequest,
)
from bisheng.workstation.domain.services.conversation_export_service import (
    ConversationExportService,
)


router = APIRouter(prefix='/chat/messages', tags=['Conversation Export'])


# Per-format MIME mapping. Used by the export endpoint to populate
# Content-Type. Keep this dict tight: it is also the source of truth for
# "what formats are accepted" (validated by the DTO enum + this map).
_MIMETYPES: dict[ExportFormat, str] = {
    ExportFormat.DOCX: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    ExportFormat.PDF: 'application/pdf',
    ExportFormat.MARKDOWN: 'text/markdown; charset=utf-8',
    ExportFormat.TXT: 'text/plain; charset=utf-8',
}


def _content_disposition_header(filename: str) -> str:
    """Build a Content-Disposition header that round-trips a UTF-8 filename.

    RFC 5987 percent-encodes the UTF-8 byte sequence and uses the
    ``filename*=UTF-8''<encoded>`` form so modern browsers preserve the
    original Chinese filename. The legacy ``filename="..."`` parameter is
    included as an ASCII-safe fallback for ancient clients (the dropped
    non-ASCII bytes are not a security concern — the user already chose
    this filename).
    """
    safe_ascii = filename.encode('ascii', errors='replace').decode('ascii').replace('?', '_')
    encoded = quote(filename, safe='')
    return f'attachment; filename="{safe_ascii}"; filename*=UTF-8\'\'{encoded}'


@router.post('/export')
async def export_messages(
    req: ExportMessagesRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Export selected messages as one of docx / pdf / md / txt.

    Always synchronous: a single conversation of up to 200 messages produces
    < 5 s end-to-end (spec §10). Response body is the raw file bytes; metadata
    travels via headers.

    Error mapping (HTTP 200 body envelope per project convention):
    - batch > 200                           → 12061
    - cross-chat / cross-user message ids   → 12062
    - missing message ids                   → 12060
    - unsupported format (defensive only — DTO enum catches it first) → 12063
    - pandoc / LibreOffice crash / timeout  → 12064
    """
    fmt = req.format
    mimetype = _MIMETYPES.get(fmt)
    if mimetype is None:
        # Defensive: the Pydantic enum should have rejected anything else.
        return ConversationExportFormatUnsupportedError.return_resp()

    # Service is responsible for raising the right *Error class; we let it
    # propagate through FastAPI's exception handlers which wrap it as a
    # UnifiedResponseModel automatically.
    filename, file_bytes = await _run_export(req, user, fmt)

    return StreamingResponse(
        iter([file_bytes]),
        media_type=mimetype,
        headers={'Content-Disposition': _content_disposition_header(filename)},
    )


async def _run_export(
    req: ExportMessagesRequest,
    user: UserPayload,
    fmt: ExportFormat,
) -> tuple[str, bytes]:
    """Orchestrate the export pipeline.

    Kept as a thin helper so the endpoint stays readable and tests can drive
    the service end-to-end without re-creating the streaming response.
    """
    messages, session = await ConversationExportService._load_and_validate_messages(
        chat_id=req.chat_id, message_ids=req.message_ids, user_id=user.user_id,
    )
    turns = ConversationExportService._build_turns(
        messages, session, user_name=user.user_name or '',
    )
    markdown = ConversationExportService._render_markdown(turns)

    if fmt == ExportFormat.DOCX:
        file_bytes = ConversationExportService._render_docx(markdown)
        ext = 'docx'
    elif fmt == ExportFormat.PDF:
        file_bytes = await ConversationExportService._render_pdf(markdown)
        ext = 'pdf'
    elif fmt == ExportFormat.MARKDOWN:
        file_bytes = markdown.encode('utf-8')
        ext = 'md'
    elif fmt == ExportFormat.TXT:
        file_bytes = ConversationExportService._render_txt(markdown)
        ext = 'txt'
    else:
        # Unreachable — enum validation guards this above.
        raise ConversationExportRenderFailedError(msg=f'unsupported format: {fmt}')

    filename = ConversationExportService._resolve_filename(session, ext)
    return filename, file_bytes


@router.post('/import-to-knowledge')
async def import_messages_to_knowledge(
    req: ImportMessagesToKnowledgeRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    space_service: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    """Generate a Markdown from the selected messages and add to the target
    knowledge space, reusing the existing upload + parse pipeline."""
    resp = await ConversationExportService.import_messages_to_knowledge(
        req, user, space_service,
    )
    return resp_200(data=resp.model_dump())
