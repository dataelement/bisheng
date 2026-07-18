"""F034 — cross-space retrieval-data migration worker.

When a file is moved to another knowledge space, ``move_items`` flips the DB
ownership synchronously and dispatches this task per file. The task moves the
file's *retrieval data* (Milvus vectors + ES chunks) from the source space's
collection/index into the target space's, re-embedding via the target space's
own model (``add_texts`` — handles differing embedding models), then deletes the
source-space copies and settles the status.

Idempotent: a re-run after a partial failure re-reads the source (already-empty
after a successful delete → no-op) and still settles REBUILDING → SUCCESS.

Image objects (``knowledge/images/{kid}/...``) are intentionally **not** moved:
chunk references keep pointing at the source-space path and resolve fine; the
objects only need migrating before the source space itself is deleted. See
design 坑 6 (follow-up).
"""

from loguru import logger

from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import ServerError
from bisheng.core.logger import trace_id_var
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileDao, KnowledgeFileStatus
from bisheng.worker.knowledge.rebuild_knowledge_worker import get_all_es_chunks
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(acks_late=True)
def migrate_file_vectors(file_id: int, source_space_id: int):
    """Move one file's retrieval data from ``source_space_id`` to its current space."""
    trace_id_var.set(f"migrate_file_vectors_{file_id}")
    logger.info("migrate_file_vectors start file_id={} source_space_id={}", file_id, source_space_id)

    db_file = KnowledgeFileDao.query_by_id_sync(file_id)
    if not db_file:
        logger.warning("migrate_file_vectors: file_id={} not found", file_id)
        return

    target_space = KnowledgeDao.query_by_id(db_file.knowledge_id)
    source_space = KnowledgeDao.query_by_id(source_space_id)
    if not target_space or not source_space:
        KnowledgeFileDao.update_file_status(
            [file_id], KnowledgeFileStatus.FAILED, "migrate: source/target space missing"
        )
        return
    if source_space.id == target_space.id:
        # Not actually cross-space (already settled by a prior run); just finalize.
        if db_file.status == KnowledgeFileStatus.REBUILDING.value:
            KnowledgeFileDao.update_file_status([file_id], KnowledgeFileStatus.SUCCESS)
        return

    try:
        _migrate_one_file(db_file, source_space, target_space)
        KnowledgeFileDao.update_file_status([file_id], KnowledgeFileStatus.SUCCESS)
        logger.info("migrate_file_vectors done file_id={} -> space={}", file_id, target_space.id)
    except BaseErrorCode as e:
        KnowledgeFileDao.update_file_status([file_id], KnowledgeFileStatus.FAILED, e.to_json_str())
    except Exception as e:
        logger.exception("migrate_file_vectors failed file_id={}: {}", file_id, str(e))
        KnowledgeFileDao.update_file_status(
            [file_id], KnowledgeFileStatus.FAILED, ServerError(exception=e).to_json_str()
        )


def _migrate_one_file(db_file: KnowledgeFile, source_space: Knowledge, target_space: Knowledge):
    source_index = source_space.index_name or source_space.collection_name
    source_es = KnowledgeRag.init_knowledge_es_vectorstore_sync(source_space)
    query = {"query": {"match": {"metadata.document_id": db_file.id}}}
    chunks = get_all_es_chunks(source_es.client, source_index, query)

    if not chunks:
        # Nothing in the source (parse never finished, or a prior run already
        # migrated and deleted). Idempotent no-op — caller finalizes the status.
        logger.info("migrate_file_vectors: no source chunks for file_id={}, nothing to move", db_file.id)
        return

    texts: list[str] = []
    metadatas: list[dict] = []
    for chunk in chunks:
        src = chunk.get("_source", {})
        text = src.get("text", "")
        metadata = dict(src.get("metadata", {}))
        metadata.pop("pk", None)  # Milvus-internal; let add_texts assign fresh pks
        metadata["knowledge_id"] = target_space.id
        texts.append(text)
        metadatas.append(metadata)

    # Write into the target space (re-embeds with the target space's model).
    target_milvus = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(db_file.user_id, knowledge=target_space)
    target_es = KnowledgeRag.init_knowledge_es_vectorstore_sync(target_space)
    target_milvus.add_texts(texts=texts, metadatas=metadatas)
    target_es.add_texts(texts=texts, metadatas=metadatas)

    # Delete the source-space copies (idempotent by document_id == file_id).
    source_es.client.delete_by_query(index=source_index, body=query)
    source_milvus = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(db_file.user_id, knowledge=source_space)
    if getattr(source_milvus, "col", None):
        try:
            source_milvus.col.delete(f"document_id == {db_file.id}")
        except Exception as e:  # best-effort: ES already moved; stale Milvus rows are filtered by knowledge_id
            logger.warning("migrate_file_vectors: source Milvus delete failed file_id={}: {}", db_file.id, str(e))
