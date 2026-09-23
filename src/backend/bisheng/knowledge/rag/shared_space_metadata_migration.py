"""共享存储迁移：复用持久化正文和向量，分批改写标识及归属。"""

import asyncio

from bisheng.knowledge.domain.contracts.shared_space_storage import ContentRelocationRequest, validate_knowledge_ids

WRITE_BATCH_SIZE = 500


async def _rows(writer, identity):
    expr = writer._doc_expr(
        tenant_id=identity.tenant_id,
        canonical_document_id=identity.canonical_document_id,
        canonical_version_id=identity.canonical_version_id,
        content_generation=identity.content_generation,
    )

    def read():
        iterator = writer.collection.query_iterator(
            batch_size=WRITE_BATCH_SIZE, expr=expr, output_fields=["*"], consistency_level="Strong"
        )
        result = []
        try:
            while page := iterator.next():
                result.extend(page)
        finally:
            iterator.close()
        return result

    return await asyncio.to_thread(read)


def _check_response(result, action):
    if result.get("errors") or result.get("failures") or result.get("timed_out"):
        raise RuntimeError(f"migration Elasticsearch {action} was incomplete")


async def relocate_content(writer, request: ContentRelocationRequest) -> None:
    from bisheng.knowledge.rag.shared_space_storage import SHARED_MILVUS_PK_FIELD, es_routing_value

    source, target = request.source, request.target
    if int(source.tenant_id) != writer.tenant_id or int(target.tenant_id) != writer.tenant_id:
        raise ValueError("migration cannot cross tenant storage routes")
    snapshot = writer._assert_writable(embedding_model_id=target.embedding_model_id)
    knowledge_ids = validate_knowledge_ids(request.knowledge_ids)
    writer._check_membership_limits(knowledge_ids)
    source_rows = await _rows(writer, source)
    target_rows = source_rows if source == target else await _rows(writer, target)
    # 完成写入后进程中断时，目标内容可作为重试来源；绝不启动解析。
    rows = source_rows or target_rows
    if not rows:
        raise RuntimeError("migration source chunks are missing; explicit content repair is required")
    if any(str(row.get("embedding_model_id")) != str(writer.schema_spec.embedding_model_id) for row in rows):
        raise RuntimeError("migration source embedding model does not match shared storage")
    if any(int(row.get("membership_generation") or 0) > request.membership_generation for row in target_rows):
        raise RuntimeError("migration membership generation is stale")
    chunks = {}
    for row in sorted(
        rows, key=lambda item: (int(item.get("membership_generation") or 0), int(item[SHARED_MILVUS_PK_FIELD]))
    ):
        chunks[int(row["chunk_index"])] = row
    rewritten = []
    for row in chunks.values():
        value = dict(row)
        value.pop(SHARED_MILVUS_PK_FIELD, None)
        value.update(
            canonical_document_id=int(target.canonical_document_id),
            canonical_version_id=int(target.canonical_version_id),
            content_file_id=int(target.content_file_id),
            content_generation=int(target.content_generation),
            knowledge_ids=list(knowledge_ids),
            knowledge_id=int(request.manager_knowledge_id or knowledge_ids[0]),
            membership_generation=request.membership_generation,
        )
        rewritten.append(value)

    index = writer._es_index(snapshot)
    for offset in range(0, len(rewritten), WRITE_BATCH_SIZE):
        page = rewritten[offset : offset + WRITE_BATCH_SIZE]
        await writer._run_milvus("insert", page)
        operations = []
        for row in page:
            header = {"_index": index, "_id": writer._es_doc_id(target, row["chunk_index"])}
            if writer._conf().es_routing_enabled:
                header["routing"] = es_routing_value(target.tenant_id, target.canonical_document_id)
            operations.extend([{"index": header}, writer._es_doc_source(row)])
        _check_response(await writer._run_es("bulk", operations=operations, refresh=True), "bulk")

    # 先写新行再删除旧主键，重试时按分块去重，不删除来源文档。
    old_pks = [int(row[SHARED_MILVUS_PK_FIELD]) for row in target_rows]
    for offset in range(0, len(old_pks), WRITE_BATCH_SIZE):
        await writer._run_milvus(
            "delete", expr=f"{SHARED_MILVUS_PK_FIELD} in {old_pks[offset : offset + WRITE_BATCH_SIZE]}"
        )
    actual = await _rows(writer, target)
    expected = {int(row["chunk_index"]): row for row in rewritten}
    if len(actual) != len(expected):
        raise RuntimeError("migration Milvus chunk count verification failed")
    for row in actual:
        want = expected.get(int(row["chunk_index"]))
        if want is None or any(
            row.get(key) != want.get(key)
            for key in ("text", "vector", "content_file_id", "knowledge_ids", "membership_generation")
        ):
            raise RuntimeError("migration Milvus content or metadata verification failed")
    query = writer._es_doc_query(
        tenant_id=target.tenant_id,
        canonical_document_id=target.canonical_document_id,
        canonical_version_id=target.canonical_version_id,
        content_generation=target.content_generation,
    )
    query["bool"]["filter"].extend(
        [
            {"term": {"metadata.content_file_id": int(target.content_file_id)}},
            {"term": {"metadata.membership_generation": request.membership_generation}},
            *[{"term": {"metadata.knowledge_ids": value}} for value in knowledge_ids],
            {
                "script": {
                    "script": {
                        "source": "doc['metadata.knowledge_ids'].length == params.n",
                        "params": {"n": len(knowledge_ids)},
                    }
                }
            },
        ]
    )
    verified = await writer._run_es("count", index=index, query=query)
    if verified.get("_shards", {}).get("failed", 0) or verified.get("count") != len(expected):
        raise RuntimeError("migration Elasticsearch metadata verification failed")
    # 合并后的目标不再检索旧主版本；来源由迁移器确认无引用后删除。
    if source != target:
        await writer._run_milvus(
            "delete",
            expr=writer._doc_expr(
                tenant_id=target.tenant_id,
                canonical_document_id=target.canonical_document_id,
                content_generation=target.content_generation,
                generation_cmp="<",
            ),
        )
        result = await writer._run_es(
            "delete_by_query",
            index=index,
            query=writer._es_doc_query(
                tenant_id=target.tenant_id,
                canonical_document_id=target.canonical_document_id,
                content_generation=target.content_generation,
                generation_lt=True,
            ),
        )
        _check_response(result, "cleanup")
