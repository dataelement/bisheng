from typing import Any

from elasticsearch import AsyncElasticsearch, Elasticsearch, helpers
from elasticsearch import exceptions as es_exceptions
from loguru import logger
from pydantic import BaseModel, Field

from bisheng.common.schemas.telemetry.base_telemetry_schema import UserContext
from bisheng.common.services import telemetry_service
from bisheng.core.search.elasticsearch.manager import get_es_connection, get_es_connection_sync

common_properties = {
    "user_id": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
    "user_name": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
    "user_group_infos": {
        "type": "nested",
        "properties": {
            "user_group_id": {
                "type": "keyword",
                "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
            },
            "user_group_name": {
                "type": "keyword",
                "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
            },
        },
    },
    "user_role_infos": {
        "type": "nested",
        "properties": {
            "role_id": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
            "role_name": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
            "group_id": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        },
    },
    "user_department_infos": {
        "type": "nested",
        "properties": {
            "department_id": {
                "type": "keyword",
                "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
            },
            "department_name": {
                "type": "keyword",
                "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
            },
        },
    },
    "timestamp": {"type": "date", "format": "strict_date_optional_time||epoch_second"},
}
common_settings = {
    "analysis": {
        "tokenizer": {
            "single_char_tokenizer": {
                "type": "ngram",
                "min_gram": 1,
                "max_gram": 1,
                "token_chars": ["letter", "digit", "punctuation", "symbol"],
            }
        },
        "analyzer": {"single_char_analyzer": {"type": "custom", "tokenizer": "single_char_tokenizer"}},
    }
}


class BaseRecord(UserContext):
    timestamp: int
    es_id: str | None = Field(default=None)


class BaseMidTable(BaseModel):
    _index_name: str = ""
    _mappings: dict[str, Any] = {}
    _es_client: AsyncElasticsearch = None
    _es_client_sync: Elasticsearch = None

    def __init__(self, ensure_sync_index: bool = True, **kwargs: Any):
        super().__init__(**kwargs)
        if ensure_sync_index:
            self.ensure_index_exists_sync()

    async def ensure_index_exists(self) -> None:
        if not self._index_name:
            return None
        if not self._es_client:
            self._es_client = await get_es_connection()
        mappings = self._mappings | common_properties
        try:
            exists = await self._es_client.indices.exists(index=self._index_name)
            if not exists:
                # Incoming body Applications Mapping
                await self._es_client.indices.create(
                    index=self._index_name, body={"settings": common_settings, "mappings": {"properties": mappings}}
                )
        except es_exceptions.RequestError as e:
            # Ignore on concurrency creation "resource_already_exists_exception"
            if "resource_already_exists_exception" not in str(e):
                logger.error(f"Failed to create ES index: {e}")
                raise e
        return None

    def ensure_index_exists_sync(self) -> None:
        if not self._index_name:
            return None
        if not self._es_client_sync:
            self._es_client_sync = get_es_connection_sync()
        mappings = self._mappings | common_properties
        try:
            exists = self._es_client_sync.indices.exists(index=self._index_name)
            if not exists:
                # Incoming body Applications Mapping
                self._es_client_sync.indices.create(
                    index=self._index_name, body={"settings": common_settings, "mappings": {"properties": mappings}}
                )
        except es_exceptions.RequestError as e:
            # Ignore on concurrency creation "resource_already_exists_exception"
            if "resource_already_exists_exception" not in str(e):
                logger.error(f"Failed to create ES index: {e}")
                raise e
        return None

    def get_latest_record_time_sync(self) -> int | None:
        """Time to fetch the last record"""
        query = {"size": 1, "sort": [{"timestamp": {"order": "desc"}}], "_source": ["timestamp"]}
        response = self._es_client_sync.search(index=self._index_name, body=query)
        hits = response.get("hits", {}).get("hits", [])
        if hits:
            latest_time = hits[0]["_source"]["timestamp"]
            return latest_time
        return None

    def insert_records_sync(self, records: list[BaseRecord]) -> None:
        """Batch Insert Record"""
        actions = []
        for rec in records:
            action = {
                "_index": self._index_name,
                "_source": rec.model_dump(exclude={"es_id"}),
            }
            if rec.es_id is not None:
                action["_id"] = rec.es_id
            actions.append(action)
        helpers.bulk(self._es_client_sync, actions)

    async def insert_record(self, record: BaseRecord) -> None:
        """异步插入单条记录。"""
        await self.ensure_index_exists()
        kwargs = {
            "index": self._index_name,
            "document": record.model_dump(exclude={"es_id"}),
        }
        if record.es_id is not None:
            kwargs["id"] = record.es_id
        await self._es_client.index(**kwargs)

    def delete_by_query_sync(
        self,
        query: dict[str, Any],
        *,
        refresh: bool = False,
        conflicts: str | None = None,
    ) -> dict[str, Any]:
        """同步删除匹配 Elasticsearch 查询的记录。"""
        self.ensure_index_exists_sync()
        kwargs = {}
        if conflicts is not None:
            kwargs["conflicts"] = conflicts
        return self._es_client_sync.delete_by_query(
            index=self._index_name,
            body={"query": query},
            refresh=refresh,
            **kwargs,
        )

    def search_from_base_sync(self, **kwargs) -> list[dict[str, Any]]:
        """Synchronize search methods"""
        response = self._es_client_sync.search(index=telemetry_service.index_name, **kwargs)
        return response.get("hits", {}).get("hits", [])
