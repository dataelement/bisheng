from typing import Dict, Any, List

from elasticsearch import Elasticsearch, AsyncElasticsearch, exceptions as es_exceptions, helpers
from loguru import logger
from pydantic import BaseModel

from bisheng.common.schemas.telemetry.base_telemetry_schema import UserContext
from bisheng.common.services import telemetry_service
from bisheng.core.search.elasticsearch.manager import get_es_connection, get_es_connection_sync

common_properties = {
    "user_id": {"type": "integer"},
    "user_name": {"type": "keyword"},
    "user_group_infos": {
        "type": "object",
        "properties": {
            "user_group_id": {"type": "integer"},
            "user_group_name": {"type": "keyword"}
        }
    },
    "user_role_infos": {
        "type": "object",
        "properties": {
            "role_id": {"type": "integer"},
            "role_name": {"type": "keyword"},
            "group_id": {"type": "integer"}
        }
    },
    "timestamp": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
}


class BaseRecord(UserContext):
    timestamp: int


class BaseMidTable(BaseModel):
    _index_name: str = ""
    _mappings: Dict[str, Any] = {}
    _es_client: AsyncElasticsearch = None
    _es_client_sync: Elasticsearch = None

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
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
                # 传入 body 应用 Mapping
                await self._es_client.indices.create(index=self._index_name,
                                                     body={"mappings": {"properties": mappings}})
        except es_exceptions.RequestError as e:
            # 并发创建时忽略 "resource_already_exists_exception"
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
                # 传入 body 应用 Mapping
                self._es_client_sync.indices.create(index=self._index_name,
                                                    body={"mappings": {"properties": mappings}})
        except es_exceptions.RequestError as e:
            # 并发创建时忽略 "resource_already_exists_exception"
            if "resource_already_exists_exception" not in str(e):
                logger.error(f"Failed to create ES index: {e}")
                raise e
        return None

    def get_latest_record_time_sync(self) -> int | None:
        """ 获取最新一条记录的时间 """
        query = {
            "size": 1,
            "sort": [{"timestamp": {"order": "desc"}}],
            "_source": ["timestamp"]
        }
        response = self._es_client_sync.search(index=self._index_name, body=query)
        hits = response.get('hits', {}).get('hits', [])
        if hits:
            latest_time = hits[0]['_source']['timestamp']
            return latest_time
        return None

    def insert_records_sync(self, records: List[BaseModel]) -> None:
        """ 批量插入记录 """
        actions = []
        for rec in records:
            action = {
                "_index": self._index_name,
                "_source": rec.model_dump()
            }
            actions.append(action)
        helpers.bulk(self._es_client_sync, actions)

    def search_from_base_sync(self, **kwargs) -> List[Dict[str, Any]]:
        """ 同步搜索方法 """
        response = self._es_client_sync.search(index=telemetry_service.index_name, **kwargs)
        return response.get('hits', {}).get('hits', [])
