"""跨文档批量读取、内存改写和批量写入共享索引。"""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from types import SimpleNamespace
from typing import Any

from bisheng.knowledge.domain.contracts.shared_space_storage import SharedProjectionWrite, validate_knowledge_ids

CHUNK_BATCH_SIZE = 500


async def _load_rows(writer: Any, document_ids: list[int]) -> list[dict]:
    def read() -> list[dict]:
        iterator = writer.collection.query_iterator(
            batch_size=CHUNK_BATCH_SIZE,
            expr=f"canonical_document_id in {document_ids}",
            output_fields=["*"],
            consistency_level="Strong",
        )
        rows = []
        try:
            while page := iterator.next():
                rows.extend(page)
        finally:
            iterator.close()
        return rows

    return await asyncio.to_thread(read)


async def apply_projection_batch(
    writer: Any,
    requests: Sequence[SharedProjectionWrite],
    *,
    guard: Callable[[], Awaitable[None]],
) -> dict[int, str]:
    from bisheng.knowledge.rag.shared_space_storage import SHARED_MILVUS_PK_FIELD, es_routing_value

    if not requests:
        return {}
    plans = {int(item.membership.canonical_document_id): item for item in requests}
    if len(plans) != len(requests):
        raise ValueError("duplicate document in projection write batch")
    if any(int(item.membership.tenant_id) != writer.tenant_id for item in requests):
        raise ValueError("projection write cannot cross tenant routes")
    snapshot = writer._assert_writable(embedding_model_id=writer.schema_spec.embedding_model_id)
    await guard()
    existing = defaultdict(list)
    for row in await _load_rows(writer, list(plans)):
        existing[int(row["canonical_document_id"])].append(row)
    rows, old_pks, errors, cleanup_queries = [], {}, {}, {}
    index = writer._es_index(snapshot)
    for document_id, plan in plans.items():
        membership = plan.membership
        previous = existing[document_id]
        try:
            knowledge_ids = validate_knowledge_ids(membership.knowledge_ids, allow_empty=True)
            writer._check_membership_limits(knowledge_ids)
            if any(int(row.get("content_generation") or 0) > membership.content_generation for row in previous):
                raise ValueError("stale projection content generation")
            if any(int(row.get("membership_generation") or 0) > membership.membership_generation for row in previous):
                raise ValueError("stale projection membership generation")
            rewritten = []
            if knowledge_ids:
                if plan.content:
                    content = plan.content
                    if (int(content.identity.tenant_id), int(content.identity.canonical_document_id)) != (
                        writer.tenant_id,
                        document_id,
                    ):
                        raise ValueError("content identity does not match projection batch")
                    writer._check_embedding_model(content.identity.embedding_model_id, snapshot)
                    rewritten = [
                        writer._build_chunk_row(
                            content.identity, chunk, knowledge_ids, membership.membership_generation
                        )
                        for chunk in content.chunks
                    ]
                    previous_to_delete = previous
                else:
                    current = [
                        row
                        for row in previous
                        if int(row.get("content_generation") or 0) == membership.content_generation
                    ]
                    if not current:
                        raise ValueError("projection content is missing; explicit content rebuild is required")
                    chunks = {}
                    for row in sorted(
                        current,
                        key=lambda item: (
                            int(item.get("membership_generation") or 0),
                            int(item[SHARED_MILVUS_PK_FIELD]),
                        ),
                    ):
                        chunks[(row["canonical_version_id"], row["chunk_index"])] = row
                    for row in chunks.values():
                        value = dict(row)
                        value.pop(SHARED_MILVUS_PK_FIELD, None)
                        value.update(
                            knowledge_ids=list(knowledge_ids), membership_generation=membership.membership_generation
                        )
                        rewritten.append(value)
                    previous_to_delete = current
                if not rewritten:
                    raise ValueError("empty content upsert is not a valid projection")
            else:
                previous_to_delete = previous
            old_pks[document_id] = [int(row[SHARED_MILVUS_PK_FIELD]) for row in previous_to_delete]
            rows.extend(rewritten)
            if not knowledge_ids:
                cleanup_queries[document_id] = writer._es_doc_query(
                    tenant_id=membership.tenant_id,
                    canonical_document_id=document_id,
                )
            elif plan.content:
                # 写入成功后才清除旧代次和同代次遗留分块。
                identity = plan.content.identity
                older = writer._es_doc_query(
                    tenant_id=membership.tenant_id,
                    canonical_document_id=document_id,
                    content_generation=membership.content_generation,
                    generation_lt=True,
                )
                extra = writer._es_doc_query(
                    tenant_id=membership.tenant_id,
                    canonical_document_id=document_id,
                    canonical_version_id=identity.canonical_version_id,
                    content_generation=membership.content_generation,
                )
                extra["bool"]["must_not"] = [
                    {"terms": {"metadata.chunk_index": [row["chunk_index"] for row in rewritten]}}
                ]
                cleanup_queries[document_id] = {"bool": {"should": [older, extra], "minimum_should_match": 1}}
        except Exception as exc:
            errors[document_id] = f"{type(exc).__name__}:{exc}"

    for offset in range(0, len(rows), CHUNK_BATCH_SIZE):
        page = [row for row in rows[offset : offset + CHUNK_BATCH_SIZE] if row["canonical_document_id"] not in errors]
        if not page:
            continue
        document_ids = {int(row["canonical_document_id"]) for row in page}
        await guard()
        writer._assert_writable(embedding_model_id=writer.schema_spec.embedding_model_id)
        try:
            # Milvus 先插入新行, ES 部分失败时保留旧主键以便重试恢复。
            await writer._run_milvus("insert", page)
            operations = []
            for row in page:
                identity = SimpleNamespace(**row)
                header = {"_index": index, "_id": writer._es_doc_id(identity, row["chunk_index"])}
                if writer._conf().es_routing_enabled:
                    header["routing"] = es_routing_value(writer.tenant_id, row["canonical_document_id"])
                operations.extend([{"index": header}, writer._es_doc_source(row)])
            response = await writer._run_es("bulk", operations=operations, refresh=True)
            items = response.get("items", [])
            if len(items) != len(page):
                raise RuntimeError("Elasticsearch bulk returned incomplete item results")
            for row, item in zip(page, items, strict=True):
                result = item.get("index", {})
                if result.get("error") or not 200 <= int(result.get("status", 0)) < 300:
                    errors[int(row["canonical_document_id"])] = "Elasticsearch bulk item failed: " + str(
                        result.get("error", result)
                    )
        except Exception as exc:
            errors.update({document_id: f"{type(exc).__name__}:{exc}" for document_id in document_ids})

    successful = set(plans) - set(errors)
    # 清理只覆盖已确认写入成功的文档; 不能因一个文档失败撤销其他文档。
    for offset in range(0, len(successful), 100):
        document_ids = sorted(successful)[offset : offset + 100]
        await guard()
        writer._assert_writable(embedding_model_id=writer.schema_spec.embedding_model_id)
        try:
            pks = [pk for document_id in document_ids for pk in old_pks.get(document_id, [])]
            for start in range(0, len(pks), CHUNK_BATCH_SIZE):
                await writer._run_milvus(
                    "delete", expr=f"{SHARED_MILVUS_PK_FIELD} in {pks[start : start + CHUNK_BATCH_SIZE]}"
                )
            queries = [cleanup_queries[document_id] for document_id in document_ids if document_id in cleanup_queries]
            if queries:
                response = await writer._run_es(
                    "delete_by_query",
                    index=index,
                    query={"bool": {"should": queries, "minimum_should_match": 1}},
                )
                if response.get("failures") or response.get("timed_out"):
                    raise RuntimeError("Elasticsearch projection cleanup incomplete")
        except Exception as exc:
            errors.update({document_id: f"{type(exc).__name__}:{exc}" for document_id in document_ids})
    return errors
