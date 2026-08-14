"""全局全文 ES 索引生命周期与写入实现。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from elasticsearch import AsyncElasticsearch, BadRequestError, NotFoundError

from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_index_repository import (
    KnowledgeFulltextIndexRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextDocument,
    KnowledgeFulltextEngagementBulkResult,
    KnowledgeFulltextEngagementCounts,
)

_ENGAGEMENT_MAPPING = {
    "preview_count": {"type": "long"},
    "download_count": {"type": "long"},
    "engagement_updated_at": {"type": "date"},
}

_ENGAGEMENT_FIELDS = frozenset(_ENGAGEMENT_MAPPING)

_SOURCE_KNOWLEDGE_MAPPING = {
    "original_knowledge_id": {"type": "long"},
    "original_knowledge_name": {"type": "keyword"},
}

_ADDITIVE_MAPPING = {**_ENGAGEMENT_MAPPING, **_SOURCE_KNOWLEDGE_MAPPING}
_ADDITIVE_MAPPING_FIELDS = frozenset(_ADDITIVE_MAPPING)

_ENGAGEMENT_UPDATE_SCRIPT = """
if ((ctx._source.preview_count ?: 0) == params.preview_count &&
    (ctx._source.download_count ?: 0) == params.download_count) {
  ctx.op = 'noop';
} else {
  ctx._source.preview_count = params.preview_count;
  ctx._source.download_count = params.download_count;
  ctx._source.engagement_updated_at = params.updated_at;
}
"""


class KnowledgeFulltextIndexConfigurationError(RuntimeError):
    """索引别名或 Mapping 与当前契约不兼容。"""


def _is_resource_already_exists_error(exc: BadRequestError) -> bool:
    error = exc.body.get("error") if isinstance(exc.body, dict) else None
    if isinstance(error, dict):
        error_type = error.get("type")
    elif isinstance(error, str):
        error_type = error
    else:
        error_type = exc.error
    return error_type == "resource_already_exists_exception"


def _normalize_index_setting(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_index_setting(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_index_setting(item) for item in value]
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return value


def _search_text_mapping(*, keyword: bool) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "substring": {
            "type": "text",
            "analyzer": "fulltext_substring_index_analyzer",
            "search_analyzer": "fulltext_substring_query_analyzer",
        }
    }
    if keyword:
        fields["keyword"] = {"type": "keyword", "ignore_above": 512}
    return {"type": "text", "analyzer": "fulltext_main_analyzer", "fields": fields}


class KnowledgeFulltextIndexRepositoryImpl(KnowledgeFulltextIndexRepository):
    def __init__(self, client: AsyncElasticsearch):
        self.client = client

    def build_index_definition(self) -> dict[str, Any]:
        text_keyword = _search_text_mapping(keyword=True)
        text_only = _search_text_mapping(keyword=False)
        keyword_text = {
            "type": "text",
            "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
        }
        properties: dict[str, Any] = {
            "file_id": {"type": "long"},
            "knowledge_id": {"type": "long"},
            "logical_document_id": {"type": "long"},
            "document_version_id": {"type": "long"},
            "content_file_id": {"type": "long"},
            "file_name": text_keyword,
            "display_title": text_keyword,
            "summary": text_only,
            "content": text_only,
            "tags": text_keyword,
            "knowledge_name": text_keyword,
            "knowledge_type": {"type": "integer"},
            "knowledge_level": {"type": "keyword"},
            "knowledge_business_domain_codes": {"type": "keyword"},
            "business_domain_code": {"type": "keyword"},
            "business_domain_name": keyword_text,
            "document_category_code": {"type": "keyword"},
            "document_category_name": keyword_text,
            "file_subcategory_code": {"type": "keyword"},
            "file_subcategory_name": keyword_text,
            "file_ext": {"type": "keyword"},
            "file_source": {"type": "keyword"},
            "folder_path": keyword_text,
            "source_path": keyword_text,
            "uploader_id": {"type": "long"},
            "uploader_name": {"type": "keyword"},
            "original_uploader_id": {"type": "long"},
            "original_uploader_name": {"type": "keyword"},
            **_SOURCE_KNOWLEDGE_MAPPING,
            "updater_id": {"type": "long"},
            "updater_name": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "entry_type": {"type": "keyword"},
            "entry_status": {"type": "keyword"},
            "projection_status": {"type": "keyword"},
            "allow_download": {"type": "boolean"},
            "chunk_count": {"type": "integer"},
            "content_hash": {"type": "keyword"},
            "index_schema_version": {"type": "integer"},
            "sync_revision": {"type": "long"},
            "indexed_at": {"type": "date"},
            **_ENGAGEMENT_MAPPING,
        }
        return {
            "settings": {
                "number_of_shards": constants.KNOWLEDGE_FULLTEXT_INDEX_SHARDS,
                "number_of_replicas": constants.KNOWLEDGE_FULLTEXT_INDEX_REPLICAS,
                "index.max_ngram_diff": constants.KNOWLEDGE_FULLTEXT_NGRAM_MAX - constants.KNOWLEDGE_FULLTEXT_NGRAM_MIN,
                "analysis": {
                    "tokenizer": {
                        "fulltext_substring_tokenizer": {
                            "type": "ngram",
                            "min_gram": constants.KNOWLEDGE_FULLTEXT_NGRAM_MIN,
                            "max_gram": constants.KNOWLEDGE_FULLTEXT_NGRAM_MAX,
                            # 保留连字符、点号等标识符字符, 空白仍作为边界。
                            "token_chars": ["letter", "digit", "punctuation", "symbol"],
                        }
                    },
                    "analyzer": {
                        "fulltext_main_analyzer": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase"],
                        },
                        "fulltext_substring_index_analyzer": {
                            "type": "custom",
                            "tokenizer": "fulltext_substring_tokenizer",
                            "filter": ["lowercase"],
                        },
                        "fulltext_substring_query_analyzer": {
                            "type": "custom",
                            "tokenizer": "keyword",
                            "filter": ["lowercase"],
                        },
                    },
                },
            },
            "mappings": {"dynamic": "strict", "properties": properties},
        }

    async def validate_read_index(self) -> None:
        """只读校验活动别名及完整索引契约, 不创建或升级任何资源。"""
        try:
            aliases = await self.client.indices.get_alias(
                name=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS
            )
        except NotFoundError as exc:
            raise KnowledgeFulltextIndexConfigurationError("stable alias does not exist") from exc
        if len(aliases) != 1:
            raise KnowledgeFulltextIndexConfigurationError(
                "stable alias must point to exactly one active index"
            )
        active_index, alias_payload = next(iter(aliases.items()))
        if active_index != constants.physical_index_name():
            raise KnowledgeFulltextIndexConfigurationError(
                f"stable alias points to incompatible index: {active_index}"
            )
        alias_definition = (alias_payload.get("aliases") or {}).get(
            constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
            {},
        )
        if alias_definition.get("is_write_index") is not True:
            raise KnowledgeFulltextIndexConfigurationError("stable alias is not the active write index")
        await self._validate_mapping(active_index, allow_additive_upgrade=False)
        await self._validate_settings(active_index)

    async def ensure_index(self) -> None:
        try:
            aliases = await self.client.indices.get_alias(name=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS)
        except NotFoundError:
            aliases = {}
        if len(aliases) > 1:
            raise KnowledgeFulltextIndexConfigurationError("stable alias points to multiple active indices")
        if aliases:
            active_index = next(iter(aliases))
            if active_index != constants.physical_index_name():
                raise KnowledgeFulltextIndexConfigurationError(
                    f"stable alias points to incompatible index: {active_index}"
                )
            await self._validate_index(active_index)
            return

        physical_index_name = constants.physical_index_name()
        exists = await self.client.indices.exists(index=physical_index_name)
        if exists:
            await self._validate_index(physical_index_name)
        else:
            try:
                await self.client.indices.create(
                    index=physical_index_name,
                    **self.build_index_definition(),
                )
            except BadRequestError as exc:
                if not _is_resource_already_exists_error(exc):
                    raise
                # 另一个 Consumer 可能在 exists 之后抢先创建, 必须校验赢家契约。
                await self._validate_index(physical_index_name)
        await self.client.indices.update_aliases(
            actions=[
                {
                    "add": {
                        "index": physical_index_name,
                        "alias": constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
                        "is_write_index": True,
                    }
                }
            ]
        )

    async def switch_alias(self, *, expected_current_index: str | None = None) -> None:
        """将稳定别名原子切换到当前配置版本。

        该方法只供受控发布/回滚流程显式调用; ``ensure_index`` 不会把别名
        自动切换到尚未完成数据准备的新物理索引。
        """
        target_index = constants.physical_index_name()
        try:
            aliases = await self.client.indices.get_alias(name=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS)
        except NotFoundError:
            aliases = {}
        if len(aliases) > 1:
            raise KnowledgeFulltextIndexConfigurationError("stable alias points to multiple active indices")

        current_index = next(iter(aliases), None)
        if expected_current_index is not None and current_index != expected_current_index:
            raise KnowledgeFulltextIndexConfigurationError(
                f"stable alias changed concurrently: expected {expected_current_index}, got {current_index}"
            )
        if current_index == target_index:
            await self._validate_index(target_index)
            return

        exists = await self.client.indices.exists(index=target_index)
        if not exists:
            await self.client.indices.create(
                index=target_index,
                **self.build_index_definition(),
            )
        else:
            await self._validate_index(target_index)

        actions: list[dict[str, Any]] = []
        if current_index is not None:
            actions.append(
                {
                    "remove": {
                        "index": current_index,
                        "alias": constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
                    }
                }
            )
        actions.append(
            {
                "add": {
                    "index": target_index,
                    "alias": constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
                    "is_write_index": True,
                }
            }
        )
        await self.client.indices.update_aliases(actions=actions)

    async def _validate_index(self, index_name: str) -> None:
        await self._validate_mapping(index_name)
        await self._validate_settings(index_name)

    async def _validate_mapping(self, index_name: str, *, allow_additive_upgrade: bool = True) -> None:
        response = await self.client.indices.get_mapping(index=index_name)
        mapping = response.get(index_name, {}).get("mappings", {})
        expected = self.build_index_definition()["mappings"]
        actual_properties = mapping.get("properties") or {}
        if mapping.get("dynamic") != "strict":
            raise KnowledgeFulltextIndexConfigurationError("existing index mapping is incompatible")
        if actual_properties == expected["properties"]:
            return

        actual_non_additive = {
            key: value for key, value in actual_properties.items() if key not in _ADDITIVE_MAPPING_FIELDS
        }
        expected_non_additive = {
            key: value for key, value in expected["properties"].items() if key not in _ADDITIVE_MAPPING_FIELDS
        }
        actual_additive = {
            key: value for key, value in actual_properties.items() if key in _ADDITIVE_MAPPING_FIELDS
        }
        expected_existing_additive = {
            key: expected["properties"][key] for key in actual_additive
        }
        if (
            actual_non_additive != expected_non_additive
            or actual_additive != expected_existing_additive
        ):
            raise KnowledgeFulltextIndexConfigurationError("existing index mapping is incompatible")

        missing_additive = {
            key: value for key, value in _ADDITIVE_MAPPING.items() if key not in actual_additive
        }
        if not allow_additive_upgrade:
            raise KnowledgeFulltextIndexConfigurationError("existing index mapping is incompatible")
        await self.client.indices.put_mapping(
            index=index_name,
            properties=missing_additive,
        )
        refreshed = await self.client.indices.get_mapping(index=index_name)
        refreshed_mapping = refreshed.get(index_name, {}).get("mappings", {})
        if (
            refreshed_mapping.get("dynamic") != "strict"
            or refreshed_mapping.get("properties") != expected["properties"]
        ):
            raise KnowledgeFulltextIndexConfigurationError("existing index mapping is incompatible")

    async def _validate_settings(self, index_name: str) -> None:
        response = await self.client.indices.get_settings(index=index_name)
        settings = response.get(index_name, {}).get("settings", {}).get("index", {})
        expected = self.build_index_definition()["settings"]
        actual_contract = {
            "max_ngram_diff": settings.get("max_ngram_diff"),
            "analysis": settings.get("analysis"),
        }
        expected_contract = {
            "max_ngram_diff": expected["index.max_ngram_diff"],
            "analysis": expected["analysis"],
        }
        if _normalize_index_setting(actual_contract) != _normalize_index_setting(expected_contract):
            raise KnowledgeFulltextIndexConfigurationError("existing index settings are incompatible")

    async def upsert(self, document: KnowledgeFulltextDocument) -> None:
        payload = document.model_dump(mode="json")
        partial_document = {key: value for key, value in payload.items() if key not in _ENGAGEMENT_FIELDS}
        await self.client.update(
            index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
            id=str(document.file_id),
            doc=partial_document,
            upsert=payload,
            retry_on_conflict=3,
            refresh=False,
        )

    async def bulk_update_engagement(
        self,
        counts: list[KnowledgeFulltextEngagementCounts],
        *,
        updated_at: datetime,
    ) -> KnowledgeFulltextEngagementBulkResult:
        if not counts:
            return KnowledgeFulltextEngagementBulkResult()
        operations: list[dict[str, Any]] = []
        for item in counts:
            operations.extend(
                [
                    {
                        "update": {
                            "_index": constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
                            "_id": str(item.file_id),
                            "retry_on_conflict": 3,
                        }
                    },
                    {
                        "script": {
                            "lang": "painless",
                            "source": _ENGAGEMENT_UPDATE_SCRIPT,
                            "params": {
                                "preview_count": item.preview_count,
                                "download_count": item.download_count,
                                "updated_at": updated_at.isoformat(),
                            },
                        }
                    },
                ]
            )
        response = await self.client.bulk(operations=operations, refresh=False)
        result = KnowledgeFulltextEngagementBulkResult()
        for response_item in response.get("items", []):
            update_result = response_item.get("update") or {}
            try:
                file_id = int(update_result.get("_id"))
            except (TypeError, ValueError):
                continue
            status = int(update_result.get("status") or 0)
            operation_result = update_result.get("result")
            if status == 404:
                result.missing_ids.append(file_id)
            elif status < 300 and operation_result == "noop":
                result.noop_ids.append(file_id)
            elif status < 300:
                result.updated_ids.append(file_id)
            else:
                result.failed_ids.append(file_id)
        return result

    async def list_file_ids(
        self,
        *,
        after_file_id: int | None,
        limit: int,
    ) -> list[int]:
        filters: list[dict[str, Any]] = []
        if after_file_id is not None:
            filters.append({"range": {"file_id": {"gt": int(after_file_id)}}})
        pit_response = await self.client.open_point_in_time(
            index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
            keep_alive="1m",
        )
        pit_id = pit_response["id"]
        try:
            response = await self.client.search(
                size=max(1, int(limit)),
                query={"bool": {"filter": filters}} if filters else {"match_all": {}},
                sort=[{"file_id": {"order": "asc"}}, "_shard_doc"],
                source_includes=["file_id"],
                pit={"id": pit_id, "keep_alive": "1m"},
            )
            pit_id = response.get("pit_id", pit_id)
        finally:
            await self.client.close_point_in_time(id=pit_id)
        file_ids: list[int] = []
        for hit in response.get("hits", {}).get("hits", []):
            try:
                file_id = int((hit.get("_source") or {}).get("file_id"))
            except (TypeError, ValueError):
                continue
            if file_id > 0:
                file_ids.append(file_id)
        return file_ids

    async def existing_file_ids(self, file_ids: list[int]) -> set[int]:
        if not file_ids:
            return set()
        if len(file_ids) > 1000:
            raise ValueError("file_ids must contain at most 1000 items")
        normalized = list(dict.fromkeys(int(file_id) for file_id in file_ids))
        if any(file_id <= 0 for file_id in normalized):
            raise ValueError("file_ids must be positive")
        response = await self.client.mget(
            index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
            ids=[str(file_id) for file_id in normalized],
            source=False,
        )
        existing: set[int] = set()
        for document in response.get("docs", []):
            if not document.get("found"):
                continue
            try:
                existing.add(int(document.get("_id")))
            except (TypeError, ValueError):
                continue
        return existing

    async def delete(self, file_id: int) -> None:
        try:
            await self.client.delete(
                index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
                id=str(file_id),
                refresh=False,
            )
        except NotFoundError:
            return

    async def delete_scope(self, knowledge_id: int) -> None:
        await self.client.delete_by_query(
            index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
            query={"term": {"knowledge_id": knowledge_id}},
            conflicts="proceed",
            refresh=False,
        )
