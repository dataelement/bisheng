"""批量核验共享正文与向量, 优先恢复已有内容而非重新解析。"""

import logging
import math
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from bisheng.knowledge.domain.contracts.shared_space_storage import (
    ContentProjectionIdentity,
    ProjectionContentInspection,
    SharedContentChunk,
)
from bisheng.knowledge.domain.contracts.shared_storage_reconcile import ReconcileQueryError
from bisheng.knowledge.rag.shared_space_projection_batch import _load_rows

logger = logging.getLogger(__name__)


async def _read_es(writer: Any, ids: list[int], guard: Callable[[], Awaitable[None]]) -> list[dict]:
    snapshot = writer._assert_writable(embedding_model_id=writer.schema_spec.embedding_model_id)
    cursor = None
    rows = []
    try:
        response = await writer._run_es(
            "search",
            index=writer._es_index(snapshot),
            query={"terms": {"metadata.canonical_document_id": ids}},
            size=500,
            sort=["_doc"],
            scroll="2m",
            source=True,
            track_total_hits=True,
            allow_partial_search_results=False,
        )
        cursor = response.get("_scroll_id")
        total = response["hits"]["total"]
        if isinstance(total, dict):
            if total.get("relation") != "eq":
                raise ReconcileQueryError("Elasticsearch hit count is not exact")
            total = total["value"]
        while True:
            cursor = response.get("_scroll_id", cursor)
            if response.get("timed_out") or response.get("_shards", {}).get("failed", 0):
                raise ReconcileQueryError("incomplete Elasticsearch content search")
            hits = response["hits"]["hits"]
            if not hits:
                break
            for hit in hits:
                source = hit["_source"]
                rows.append({**source["metadata"], "text": source.get("text")})
            if len(rows) > total:
                raise ReconcileQueryError("Elasticsearch content pages exceed hit count")
            if not cursor:
                raise ReconcileQueryError("missing Elasticsearch content scroll cursor")
            await guard()
            response = await writer._run_es("scroll", scroll_id=cursor, scroll="2m")
        if len(rows) != total:
            raise ReconcileQueryError("incomplete Elasticsearch content pages")
        return rows
    finally:
        if cursor:
            try:
                await writer._run_es("clear_scroll", scroll_id=cursor)
            except Exception:
                logger.warning("projection content scroll cleanup failed", exc_info=True)


def _valid_vector(value: Any, dimension: int) -> bool:
    try:
        return value is not None and len(value) == dimension and all(math.isfinite(v) for v in value)
    except (TypeError, ValueError):
        return False


def inspect_content(
    identity: ContentProjectionIdentity,
    milvus: list[dict],
    es: list[dict],
    dimension: int,
) -> ProjectionContentInspection:
    """版本、来源、分块连续性、正文一致性和向量有效性共同决定恢复方式。"""
    selected = {"milvus": {}, "es": {}}
    expected = {
        "canonical_document_id": identity.canonical_document_id,
        "canonical_version_id": identity.canonical_version_id,
        "content_file_id": identity.content_file_id,
        "content_generation": identity.content_generation,
    }
    for side, rows in (("milvus", milvus), ("es", es)):
        for row in rows:
            if int(row.get("content_generation") or 0) > identity.content_generation:
                return ProjectionContentInspection("defer", "newer content generation exists")
            if any(row.get(key) != value for key, value in expected.items()):
                continue
            index = row.get("chunk_index")
            if type(index) is not int or index < 0 or not isinstance(row.get("text"), str):
                return ProjectionContentInspection("defer", "invalid stored chunk identity or text")
            old = selected[side].get(index)
            if old and old["text"] != row["text"]:
                return ProjectionContentInspection("defer", "duplicate chunks contain conflicting text")
            # 重试产生的重复行允许复用, 优先保留有效的同模型向量。
            valid = str(row.get("embedding_model_id")) == str(identity.embedding_model_id) and _valid_vector(
                row.get("vector"), dimension
            )
            if old is None or (side == "milvus" and valid):
                selected[side][index] = row
    vector_rows, text_rows = selected["milvus"], selected["es"]
    for index in vector_rows.keys() & text_rows.keys():
        if vector_rows[index]["text"] != text_rows[index]["text"]:
            return ProjectionContentInspection("defer", "Elasticsearch and Milvus text conflict")
    combined = {**text_rows, **vector_rows}
    if not combined:
        return ProjectionContentInspection("rebuild", "target version content missing from both stores")
    indexes = sorted(combined)
    if indexes != list(range(len(indexes))):
        return ProjectionContentInspection("rebuild", "stored content has unrecoverable chunk gaps")
    chunks = []
    for index in indexes:
        row = combined[index]
        vector_row = vector_rows.get(index, {})
        vector = vector_row.get("vector")
        if str(vector_row.get("embedding_model_id")) != str(identity.embedding_model_id) or not _valid_vector(
            vector, dimension
        ):
            vector = None
        metadata = {key: value for key, value in row.items() if key not in {"pk", "text", "vector"}}
        chunks.append(SharedContentChunk(index, row["text"], vector=vector, metadata=metadata))
    if any(chunk.vector is None for chunk in chunks):
        return ProjectionContentInspection("embed", "reuse stored text and regenerate missing vectors", tuple(chunks))
    return ProjectionContentInspection("reuse", "reuse verified stored text and vectors", tuple(chunks))


async def inspect_projection_content(
    writer: Any,
    identities: Sequence[ContentProjectionIdentity],
    *,
    guard: Callable[[], Awaitable[None]],
) -> dict[int, ProjectionContentInspection]:
    if not identities:
        return {}
    if any(int(item.tenant_id) != writer.tenant_id for item in identities):
        raise ValueError("projection content inspection cannot cross tenants")
    ids = [int(item.canonical_document_id) for item in identities]
    writer._assert_writable(embedding_model_id=writer.schema_spec.embedding_model_id)
    dimension = next(
        (int(field.params["dim"]) for field in writer.collection.schema.fields if field.name == "vector"),
        0,
    )
    if dimension <= 0:
        raise ReconcileQueryError("shared vector dimension is unavailable")
    await guard()
    # 任一查询异常都向上抛出, 不能拿另一端数据或空结果触发重新解析。
    milvus_rows = await _load_rows(writer, ids)
    es_rows = await _read_es(writer, ids, guard)
    grouped = {"milvus": defaultdict(list), "es": defaultdict(list)}
    for side, rows in (("milvus", milvus_rows), ("es", es_rows)):
        for row in rows:
            document_id = int(row["canonical_document_id"])
            if document_id not in ids:
                raise ReconcileQueryError("unexpected document in content query")
            grouped[side][document_id].append(row)
    results = {}
    for identity in identities:
        document_id = identity.canonical_document_id
        try:
            results[document_id] = inspect_content(
                identity,
                grouped["milvus"][document_id],
                grouped["es"][document_id],
                dimension,
            )
        except (TypeError, ValueError, KeyError) as exc:
            results[document_id] = ProjectionContentInspection("defer", f"invalid stored content: {exc}")
    return results
