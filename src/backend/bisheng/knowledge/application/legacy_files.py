"""Original document-file protocols backed by the native SPACE upload owner."""

import json
from copy import deepcopy
from hashlib import sha256

from loguru import logger
from starlette.concurrency import run_in_threadpool

from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeFileFailedError, KnowledgeInvalidCursorError
from bisheng.common.schemas.api import PageInfiniteCursorData
from bisheng.knowledge.application.space_upload import make_space_upload_application
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao, KnowledgeFileStatus
from bisheng.knowledge.domain.repositories.legacy_file_read_repository import LegacyFileReadRepository
from bisheng.permission.application.identity import resolve_permission_actor


def make_legacy_space_service(request, identity):
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    service = KnowledgeSpaceService(request, identity)
    service.upload_application_factory = lambda: make_space_upload_application(service)
    return service


class LegacyFilesApplication:
    def __init__(self, *, request, identity):
        self.request, self.identity = request, identity
        self.service = make_legacy_space_service(request, identity)

    async def aregister(self, command, *, trusted_sources=None):
        """Register a whole batch once, without enqueueing an inline ingestion.

        ``trusted_sources`` are server-resolved upload references, one per
        file_list item; when given, only those objects are read.
        """
        from bisheng.knowledge.domain.services.knowledge_space_service import _UploadDispatchBatch

        fixed = deepcopy(command)
        application = self.service.upload_application_factory()
        batch = _UploadDispatchBatch()
        knowledge = await KnowledgeDao.aquery_by_id(fixed.knowledge_id)
        with self.service._upload_execution_scope(knowledge):
            try:
                result = await self.service.add_file(
                    fixed.knowledge_id,
                    [one.file_path for one in fixed.file_list],
                    _legacy_inputs=tuple(fixed.file_list),
                    _legacy_request=fixed,
                    _application=application,
                    _deferred=batch,
                    **({"trusted_sources": trusted_sources} if trusted_sources is not None else {}),
                )
            except BaseException:
                await self.service._compensate_upload(application)
                raise
        failed = [row for row in result if self._status(row) == KnowledgeFileStatus.FAILED.value]
        return application, batch, failed

    async def astage(self, command, *, trusted_sources=None):
        _application, batch, failed = await self.aregister(command, trusted_sources=trusted_sources)
        return (
            await KnowledgeDao.aquery_by_id(command.knowledge_id),
            failed,
            await self._aread_registered(batch, knowledge_id=command.knowledge_id),
            [cache for _row, cache in batch.files],
        )

    async def aprocess(self, command, *, inline=False, documents=None, trusted_sources=None):
        from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

        fixed = deepcopy(command)
        knowledge = await KnowledgeDao.aquery_by_id(fixed.knowledge_id)
        if trusted_sources is not None and inline:
            raise ValueError("Trusted upload sources are not supported for inline ingestion")
        if not inline:
            result = await self.service.add_file(
                fixed.knowledge_id,
                [one.file_path for one in fixed.file_list],
                _legacy_inputs=tuple(fixed.file_list),
                _legacy_request=fixed,
                callback_url=fixed.callback_url,
                **({"trusted_sources": trusted_sources} if trusted_sources is not None else {}),
            )
            process_files = [row for row in result if self._status(row) != KnowledgeFileStatus.FAILED.value]
        else:
            # Preserve the upload owner's exact original scope throughout its
            # own compensation. This holds no SQL Session during index IO.
            with self.service._upload_execution_scope(knowledge):
                result, process_files = await self._ainline(knowledge, fixed, documents)
        await run_in_threadpool(
            KnowledgeService.upload_knowledge_file_hook, self.request, self.identity, knowledge, process_files
        )
        return result

    @staticmethod
    def _status(row):
        return row["status"] if isinstance(row, dict) else row.status

    @staticmethod
    async def _aread_registered(batch, *, knowledge_id):
        ids = [row.id for row, _cache in batch.files]
        rows = await KnowledgeFileDao.aget_file_by_ids(ids) if ids else []
        by_id = {row.id: row for row in rows}
        if len(by_id) != len(ids) or any(
            row.knowledge_id != knowledge_id or row.tenant_id != original.tenant_id
            for original, _cache in batch.files
            for row in (by_id.get(original.id),)
            if row is not None
        ):
            raise KnowledgeFileFailedError()
        return [by_id[ident] for ident in ids]

    async def _ainline(self, knowledge, fixed, documents):
        from bisheng.api.services.knowledge_imp import delete_vector_files, process_file_task, text_knowledge

        application, batch, failed = await self.aregister(fixed)
        process_files = await self._aread_registered(batch, knowledge_id=knowledge.id)
        if process_files and documents is None:
            await run_in_threadpool(
                process_file_task,
                knowledge=knowledge,
                db_files=process_files,
                preview_cache_keys=[cache for _row, cache in batch.files],
                callback_url=fixed.callback_url,
            )
        elif process_files:
            try:
                await run_in_threadpool(text_knowledge, knowledge, process_files[0], documents)
            except BaseException as exc:
                try:
                    await run_in_threadpool(delete_vector_files, [row.id for row in process_files], knowledge)
                    await application.arollback_created()
                except BaseException:
                    # Keep the original ingestion error. Uncertain cleanup
                    # retains the owned chain for explicit reconciliation.
                    logger.opt(exception=True).error("Legacy SPACE text ingestion cleanup requires reconciliation")
                if isinstance(exc, Exception) and not isinstance(exc, BaseErrorCode):
                    raise KnowledgeFileFailedError(exception=exc) from exc
                raise
        process_files = await self._aread_registered(batch, knowledge_id=knowledge.id)
        if any(row.status != KnowledgeFileStatus.SUCCESS.value for row in process_files):
            raise KnowledgeFileFailedError()
        return failed + process_files, process_files

    async def alist(
        self,
        *,
        knowledge,
        decorate,
        keyword=None,
        status=None,
        file_ids=None,
        page=1,
        page_size=10,
        cursor=None,
        use_cursor=False,
    ):
        await self.service._require_action("knowledge_space", knowledge.id, "visible")
        repo = LegacyFileReadRepository()
        context = {"permissions": {}, "verified_space": knowledge}
        args = {"space_id": knowledge.id, "keyword": keyword, "status": status, "file_ids": file_ids}
        if use_cursor:
            actor = await resolve_permission_actor(self.identity)
            digest = sha256(json.dumps([keyword, status, file_ids], sort_keys=True).encode()).hexdigest()
            signature = f"legacy_space_files|{actor.tenant_id}|{actor.subject_type}:{actor.subject_id}|{actor.data_scope}|{knowledge.id}|{digest}"
            try:
                decoded = decode_cursor(cursor, expected_key_len=1, expected_context=signature)
            except CursorDecodeError as exc:
                raise KnowledgeInvalidCursorError() from exc
            after = decoded[0] if decoded else None
            if after is not None and (type(after) is not int or after <= 0):
                raise KnowledgeInvalidCursorError()
            selected, scanned, more = [], 0, True
            while len(selected) < page_size and scanned < 1000 and more:
                batch = await repo.acandidates(**args, after=after, limit=min(100, 1000 - scanned))
                more = bool(batch)
                if not batch:
                    break
                visible = {
                    row.id
                    for row in await self.service._filter_visible_child_items(
                        batch, space_id=knowledge.id, context=context
                    )
                }
                for row in batch:
                    scanned += 1
                    after = row.id
                    if row.id in visible:
                        selected.append(row)
                    if len(selected) == page_size:
                        break
                context["permissions"].clear()
                # A continuation is safe even when its next page is empty.
                more = len(batch) == 100 or len(selected) == page_size
            result = PageInfiniteCursorData(
                data=await decorate(knowledge, selected),
                page_size=page_size,
                has_more=more,
                next_cursor=encode_cursor((after,), context=signature) if more and after is not None else None,
            )
        else:
            after, total, selected = None, 0, []
            offset = max(0, page - 1) * page_size
            unpaged = not (page and page_size)
            while True:
                batch = await repo.acandidates(**args, after=after, order="update")
                if not batch:
                    break
                visible = await self.service._filter_visible_child_items(batch, space_id=knowledge.id, context=context)
                for row in visible:
                    if unpaged or offset <= total < offset + page_size:
                        selected.append(row)
                    total += 1
                after = (batch[-1].update_time, batch[-1].id)
                # Do not retain the previous pages' permission IDs.
                context["permissions"].clear()
                if len(batch) < 100:
                    break
            result = (await decorate(knowledge, selected), total)
        return result, await self.service.can_write_space_container(knowledge.id)
