"""Retry old collection purges from the existing committed task ledger."""

import asyncio

from loguru import logger

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.repositories.processing_fence_repository import ProcessingFenceRepository
from bisheng.knowledge.domain.repositories.rebuild_cleanup_repository import RebuildCleanupRepository
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


def _drop(name):
    # Use the configured connection, without constructing a live embedding.
    from bisheng.core.ai import FakeEmbeddings

    vector = KnowledgeRag.init_milvus_vectorstore(name, FakeEmbeddings())
    if vector.col is not None:
        vector.col.drop()


async def cleanup_rebuild_collections(sessions):
    repository = RebuildCleanupRepository()
    after, count = None, 0
    while True:
        async with sessions() as session:
            ids = await repository.acandidates(session, after=after)
        for ident in ids:
            material = None
            try:
                async with sessions() as session:
                    material = await repository.aread(session, ident)
                if material is not None:
                    async with ProcessingFenceRepository(async_sessions=sessions).cleanup(material):
                        async with sessions() as session:
                            actual = await repository.aread(session, ident)
                        if actual is not None:
                            await asyncio.to_thread(_drop, actual.name)
                            async with sessions() as session:
                                await repository.amark(session, actual)
                                await session.commit()
                            count += 1
            except Exception as error:
                logger.exception("Superseded vector collection cleanup failed cleanup={}", ident)
                if material is not None:
                    async with sessions() as session:
                        await repository.amark(session, material, error_type=type(error).__name__[:128])
                        await session.commit()
            after = ident
        if len(ids) < 100:
            return count


CLEANUP_TASK = "bisheng.worker.knowledge.rebuild_cleanup.cleanup_superseded_collections"


@bisheng_celery.task(name=CLEANUP_TASK, acks_late=True)
def cleanup_superseded_collections():
    return run_async_task(lambda: cleanup_rebuild_collections(get_async_db_session))
