"""Authorize recall content through its live message/session and source resources."""

import asyncio
import json

from starlette.concurrency import run_in_threadpool

from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.knowledge import BackendProcessingError
from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids
from bisheng.knowledge.domain.repositories.qa_recall_repository import QaRecallRepository
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.permission.application.business_authorization import require_business_action


class QaRecallService:
    @classmethod
    async def _parent(cls, user, message_id):
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise NotFoundError.http_exception()
        parent = await run_in_threadpool(QaRecallRepository.parent, message_id)
        if parent is None:
            raise NotFoundError.http_exception()
        message, session = parent
        if (
            message.tenant_id != tenant_id
            or session.tenant_id != tenant_id
            or message.chat_id != session.chat_id
            or message.flow_id != session.flow_id
            or message.user_id != session.user_id
            or session.is_delete
        ):
            raise NotFoundError.http_exception()
        if session.user_id != user.user_id or session.api_subject_type is not None:
            # Keep the existing audit/annotation entitlement rather than granting
            # every logged-in caller a conversation read. This legacy adapter is
            # also used by the audit detail endpoint; no raw permission queries.
            await AuditLogService.assert_session_in_audit_scope(
                user,
                session.chat_id,
                session_owner_id=session.user_id if session.api_subject_type is None else None,
                app_id=session.flow_id,
            )
        return session

    @classmethod
    async def _chunks(cls, user, message_id):
        session = await cls._parent(user, message_id)
        chunks = await run_in_threadpool(QaRecallRepository.chunks, message_id, session.chat_id)
        # Defense against inconsistent historical parent references.
        return [row for row in chunks if row.message_id == message_id and row.chat_id == session.chat_id]

    @classmethod
    async def keywords(cls, user, message_id):
        for attempt in range(4):
            chunks = await cls._chunks(user, message_id)
            if chunks:
                return json.loads(chunks[0].keywords)
            if attempt < 3:
                await asyncio.sleep(1)
        raise BackendProcessingError()

    @classmethod
    async def original_files(cls, user, message_id, keys):
        chunks = await cls._chunks(user, message_id)
        if not chunks:
            return []
        files = await run_in_threadpool(QaRecallRepository.files, {row.file_id for row in chunks if row.file_id})
        tenant_id = get_current_tenant_id()
        # Source resources may be explicitly shared from Root to a child tenant;
        # conversation-derived rows remain strict-leaf, while source visibility
        # follows the middleware's visible tenants plus the current action check.
        source_tenants = get_visible_tenant_ids() or frozenset({tenant_id})
        id_to_file = {file.id: file for file in files if file.tenant_id in source_tenants}
        allowed = {}
        denied = set()
        # Authorize before exposing bbox, name, id, or links. Denied files stay in
        # the payload with right=False so the UI can show a permission tip instead
        # of an empty source panel.
        for file_id, file in id_to_file.items():
            try:
                await require_business_action(
                    user, resource_type="knowledge_file", resource_id=file_id, action="download"
                )
            except UnAuthorizedError:
                denied.add(file_id)
                continue
            allowed[file_id] = file
        result = []
        keywords = keys.split(";") if keys else []
        signed = {}
        for chunk in chunks:
            metadata = json.loads(chunk.meta_data) if chunk.meta_data else {}
            if not metadata.get("right", True):
                continue
            file = allowed.get(chunk.file_id)
            if file is None:
                if chunk.file_id not in denied and chunk.file_id not in id_to_file:
                    continue
                row = json.loads(metadata["bbox"]) if metadata.get("bbox") else {}
                denied_name = getattr(id_to_file.get(chunk.file_id), "file_name", None) or "masked"
                row.update(
                    right=False,
                    preview_url="",
                    original_url="",
                    source=denied_name,
                    score=round(match_score(chunk.chunk, keywords), 2) if keywords else 0,
                    file_id=chunk.file_id,
                    parse_type=getattr(id_to_file.get(chunk.file_id), "parse_type", None),
                )
                result.append(row)
                continue
            if file.id not in signed:
                signed[file.id] = await run_in_threadpool(KnowledgeService.get_file_share_url, file=file)
            original_url, preview_url = signed[file.id]
            row = json.loads(metadata["bbox"]) if metadata.get("bbox") else {}
            row.update(
                right=True,
                preview_url=preview_url,
                original_url=original_url,
                source=file.file_name,
                score=round(match_score(chunk.chunk, keywords), 2) if keywords else 0,
                file_id=file.id,
                parse_type=file.parse_type,
            )
            result.append(row)
        return result


def match_score(chunk, keywords):
    hits = 0
    for keyword in keywords:
        previous = [0] * (len(keyword) + 1)
        longest = 0
        for char in chunk or "":
            current = [0] * (len(keyword) + 1)
            for index, other in enumerate(keyword, 1):
                if char == other:
                    current[index] = previous[index - 1] + 1
                    longest = max(longest, current[index])
            previous = current
        hits += longest >= 2 / 3 * len(keyword)
    return hits / len(keywords)
