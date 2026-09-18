"""已授权空间的共享分块查询；返回当前空间条目而非内容文件 ID。"""

from bisheng.core.database import get_async_db_session
from bisheng.core.search.elasticsearch.manager import get_es_connection
from bisheng.knowledge.domain.contracts.errors import SharedStorageContractError, SharedStorageErrorCode
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import KnowledgeFileRepositoryImpl
from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import KnowledgeDocumentEntryResolver
from bisheng.knowledge.rag.shared_space_storage import aresolve_space_shared_routing


async def search_shared_space_file_ids(*, spaces, keyword: str, filter_file_ids=None) -> list[int]:
    """按共享正文匹配文件；调用方继续执行原有文件权限与列表过滤。"""
    if not spaces or not keyword or filter_file_ids == []:
        return []
    tenant_id = int(spaces[0].tenant_id or 1)
    if any(int(space.tenant_id or 1) != tenant_id or space.type != KnowledgeTypeEnum.SPACE.value for space in spaces):
        raise SharedStorageContractError(SharedStorageErrorCode.SCOPE_SPACE_NOT_VISIBLE, "cross tenant chunk query")
    route = await aresolve_space_shared_routing(tenant_id, spaces[0].type)
    if route is None:
        raise SharedStorageContractError(SharedStorageErrorCode.ROUTING_NOT_CONFIGURED, "SPACE shared route required")
    space_ids = [int(space.id) for space in spaces]
    client = await get_es_connection()
    response = await client.search(
        index=route.index_name,
        query={"bool": {
            "must": [{"match_phrase": {"text": keyword}}],
            "filter": [{"terms": {"metadata.knowledge_ids": space_ids}}],
        }},
        size=0,
        aggs={"documents": {"terms": {"field": "metadata.canonical_document_id", "size": 10000},
                            "aggs": {"generation": {"max": {"field": "metadata.content_generation"}}}}},
    )
    generations = {
        int(bucket["key"]): int(bucket["generation"]["value"])
        for bucket in response.get("aggregations", {}).get("documents", {}).get("buckets", [])
        if bucket.get("generation", {}).get("value") is not None
    }
    if not generations:
        return []
    allowed = set(filter_file_ids) if filter_file_ids is not None else None
    result = []
    async with get_async_db_session() as session:
        repository = KnowledgeFileRepositoryImpl(session)
        document_ids = list(generations)
        for offset in range(0, len(document_ids), 200):
            entries = await repository.find_active_entries_for_documents(
                tenant_id=tenant_id, document_ids=document_ids[offset:offset + 200], knowledge_ids=space_ids,
            )
            result.extend(
                int(entry.id) for entry in entries
                if int(entry.tenant_id or 1) == tenant_id
                and int(entry.knowledge_id) in space_ids
                and entry.status == KnowledgeFileStatus.SUCCESS.value
                and entry.deleted_at is None
                and KnowledgeDocumentEntryResolver._projection_ready(entry)
                and int(entry.desired_content_generation) == generations.get(int(entry.reference_document_id or 0))
                and (allowed is None or int(entry.id) in allowed)
            )
    return list(dict.fromkeys(result))
