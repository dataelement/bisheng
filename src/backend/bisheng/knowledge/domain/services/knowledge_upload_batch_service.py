"""Upload-confirmation batches and the similarity repair that runs after parse commit."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, delete, select

from bisheng.common.errcode.knowledge_space import UploadBatchKeyRejectedError
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_file_similarity_candidate import KnowledgeFileSimilarityCandidate
from bisheng.knowledge.domain.models.knowledge_upload_batch import KnowledgeUploadBatch, KnowledgeUploadBatchFile

Schedule = Callable[[int, int], None]


class UploadBatchEpochStale(Exception):
    """The similarity result belongs to an older batch revision and must not be stored."""


def canonical_batch_key(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) != 36:
        raise UploadBatchKeyRejectedError()
    try:
        parsed = UUID(text)
    except ValueError as exc:
        raise UploadBatchKeyRejectedError() from exc
    if str(parsed) != text.lower():
        raise UploadBatchKeyRejectedError()
    return str(parsed)


async def prepare_upload_batch(
    *,
    tenant_id: int,
    knowledge_id: int,
    user_id: int,
    upload_batch_key: str | None,
) -> int:
    """Return the batch id. Reject a key that cannot be used, without creating files."""
    key = canonical_batch_key(upload_batch_key) or str(uuid4())
    async with get_async_db_session() as session:
        batch = (
            await session.exec(
                select(KnowledgeUploadBatch).where(
                    KnowledgeUploadBatch.tenant_id == tenant_id,
                    KnowledgeUploadBatch.batch_key == key,
                )
            )
        ).first()
        if batch is not None:
            if batch.knowledge_id != knowledge_id or batch.created_by != user_id:
                raise UploadBatchKeyRejectedError()
            return int(batch.id)
        batch = KnowledgeUploadBatch(
            tenant_id=tenant_id,
            knowledge_id=knowledge_id,
            batch_key=key,
            created_by=user_id,
            revision=0,
        )
        session.add(batch)
        try:
            await session.commit()
            await session.refresh(batch)
        except IntegrityError:
            await session.rollback()
            batch = (
                await session.exec(
                    select(KnowledgeUploadBatch).where(
                        KnowledgeUploadBatch.tenant_id == tenant_id,
                        KnowledgeUploadBatch.batch_key == key,
                    )
                )
            ).first()
            if batch is None or batch.knowledge_id != knowledge_id or batch.created_by != user_id:
                raise UploadBatchKeyRejectedError()
            return int(batch.id)
        return int(batch.id)


async def attach_upload_batch_file(*, batch_id: int, file_id: int, tenant_id: int) -> None:
    async with get_async_db_session() as session:
        existing = (
            await session.exec(select(KnowledgeUploadBatchFile).where(KnowledgeUploadBatchFile.file_id == file_id))
        ).first()
        if existing is not None:
            return
        session.add(KnowledgeUploadBatchFile(tenant_id=tenant_id, batch_id=batch_id, file_id=file_id))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()


async def delete_upload_batch_members(file_ids: list[int]) -> None:
    if not file_ids:
        return
    async with get_async_db_session() as session:
        await session.exec(delete(KnowledgeUploadBatchFile).where(col(KnowledgeUploadBatchFile.file_id).in_(file_ids)))
        await session.commit()


async def bump_upload_batch_revision(batch_id: int) -> int:
    async with get_async_db_session() as session:
        batch = (
            await session.exec(
                select(KnowledgeUploadBatch).where(KnowledgeUploadBatch.id == batch_id).with_for_update()
            )
        ).one()
        batch.revision = int(batch.revision or 0) + 1
        batch.update_time = datetime.now()
        session.add(batch)
        await session.commit()
        await session.refresh(batch)
        return int(batch.revision)


async def find_upload_batch_id(file_id: int) -> int | None:
    async with get_async_db_session() as session:
        member = (
            await session.exec(select(KnowledgeUploadBatchFile).where(KnowledgeUploadBatchFile.file_id == file_id))
        ).first()
        if member is None:
            return None
        return int(member.batch_id)


async def list_upload_batch_file_ids(batch_id: int) -> list[int]:
    async with get_async_db_session() as session:
        rows = (
            await session.exec(
                select(KnowledgeUploadBatchFile.file_id)
                .where(KnowledgeUploadBatchFile.batch_id == batch_id)
                .order_by(KnowledgeUploadBatchFile.file_id)
            )
        ).all()
        return [int(file_id) for file_id in rows]


async def commit_similarity_if_epoch(
    version_service,
    file_id: int,
    rows: list[KnowledgeFileSimilarityCandidate],
    snapshot: dict | None,
    has_candidates: bool,
    *,
    batch_id: int,
    epoch: int,
) -> str:
    """Replace candidates only while the batch revision still matches."""
    session = version_service.knowledge_file_repo.session
    batch = (
        await session.exec(select(KnowledgeUploadBatch).where(KnowledgeUploadBatch.id == batch_id).with_for_update())
    ).first()
    if batch is None or int(batch.revision or 0) != epoch:
        await session.rollback()
        return "stale"
    current = (await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == file_id).with_for_update())).first()
    if current is None or current.similar_status == 2:
        await session.rollback()
        return "skipped"
    await session.exec(
        delete(KnowledgeFileSimilarityCandidate).where(KnowledgeFileSimilarityCandidate.source_file_id == file_id)
    )
    if rows:
        session.add_all(rows)
    if snapshot is not None:
        current.user_metadata = {**(current.user_metadata or {}), "_similarity_snapshot": snapshot}
    current.similar_status = 1 if has_candidates else 0
    session.add(current)
    await session.commit()
    return "written"


def _default_schedule(batch_id: int, epoch: int) -> None:
    from bisheng.worker.knowledge.upload_batch_similarity import reconcile_upload_batch_similarity

    reconcile_upload_batch_similarity.delay(batch_id, epoch)


async def _refresh_file(file_id: int, batch_epoch: tuple[int, int] | None) -> int:
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
        KnowledgeDocumentRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
        KnowledgeFileRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_similarity_candidate_repository_impl import (
        KnowledgeFileSimilarityCandidateRepositoryImpl,
    )
    from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService

    async with get_async_db_session() as session:
        service = KnowledgeVersionService(
            request=None,
            login_user=None,
            doc_repo=KnowledgeDocumentRepositoryImpl(session),
            version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
            knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
            similar_candidate_repo=KnowledgeFileSimilarityCandidateRepositoryImpl(session),
        )
        if batch_epoch is None:
            return await service.refresh_similar_candidates_for_file(file_id)
        return await service.refresh_similar_candidates_for_file(file_id, batch_epoch=batch_epoch)


async def finish_parsed_file_similarity(
    file_id: int,
    *,
    schedule: Schedule | None = None,
) -> None:
    """Called after the parse status commit. Files without a batch only refresh themselves."""
    batch_id = await find_upload_batch_id(file_id)
    if batch_id is None:
        await _refresh_file(file_id, None)
        return
    epoch = await bump_upload_batch_revision(batch_id)
    try:
        await _refresh_file(file_id, (batch_id, epoch))
    except UploadBatchEpochStale:
        logger.info(
            "upload batch similarity epoch moved file_id={} batch_id={} epoch={}",
            file_id,
            batch_id,
            epoch,
        )
    except Exception:
        logger.exception("upload batch self similarity failed file_id={}", file_id)
    try:
        (schedule or _default_schedule)(batch_id, epoch)
    except Exception:
        logger.exception(
            "upload batch similarity schedule failed file_id={} batch_id={}",
            file_id,
            batch_id,
        )


def run_similarity_after_parse(
    file_id: int, *, runner: Callable[[Callable[[], Awaitable[None]]], None] | None = None
) -> None:
    if runner is None:
        from bisheng.worker._asyncio_utils import run_async_task

        runner = run_async_task
    try:
        runner(lambda: finish_parsed_file_similarity(file_id))
    except Exception:
        logger.exception("inline similarity candidate refresh failed file_id={}", file_id)


async def _file_ready_for_batch_similarity(file_id: int) -> bool:
    async with get_async_db_session() as session:
        current = await session.get(KnowledgeFile, file_id)
        if current is None or current.deleted_at is not None:
            return False
        if current.status != KnowledgeFileStatus.SUCCESS.value or current.similar_status == 2:
            return False
        return True


async def reconcile_upload_batch(batch_id: int, epoch: int) -> str:
    async with get_async_db_session() as session:
        batch = await session.get(KnowledgeUploadBatch, batch_id)
        if batch is None or int(batch.revision or 0) != epoch:
            return "skipped"
    for file_id in await list_upload_batch_file_ids(batch_id):
        async with get_async_db_session() as session:
            batch = await session.get(KnowledgeUploadBatch, batch_id)
            if batch is None or int(batch.revision or 0) != epoch:
                return "skipped"
        if not await _file_ready_for_batch_similarity(file_id):
            continue
        try:
            await _refresh_file(file_id, (batch_id, epoch))
        except UploadBatchEpochStale:
            return "skipped"
    return "done"
