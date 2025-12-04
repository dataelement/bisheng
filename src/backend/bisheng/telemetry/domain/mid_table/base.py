from typing import Dict, Any

from elasticsearch import Elasticsearch, AsyncElasticsearch, exceptions as es_exceptions
from loguru import logger
from pydantic import BaseModel

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
    }
}


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
