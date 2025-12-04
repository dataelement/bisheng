from typing import Dict, Any, List

from elasticsearch import helpers
from pydantic import Field

from bisheng.common.schemas.telemetry.base_telemetry_schema import UserContext
from .base import BaseMidTable


class UserIncrementRecord(UserContext):
    create_time: int = Field(..., description="Create timestamp of the user")


class UserIncrement(BaseMidTable):
    _index_name: str = 'mid_user_increment'
    _mappings: Dict[str, Any] = {
        "create_time": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
    }

    def get_latest_record_time(self) -> int | None:
        """ 获取最新一条记录的时间 """
        query = {
            "size": 1,
            "sort": [{"create_time": {"order": "desc"}}],
            "_source": ["create_time"]
        }
        response = self._es_client_sync.search(index=self._index_name, body=query)
        hits = response.get('hits', {}).get('hits', [])
        if hits:
            latest_time = hits[0]['_source']['create_time']
            return latest_time
        return None

    def insert_record(self, record: List[UserIncrementRecord]) -> None:
        """ 插入用户增量记录 """
        actions = []
        for rec in record:
            action = {
                "_index": self._index_name,
                "_source": rec.model_dump()
            }
            actions.append(action)
        helpers.bulk(self._es_client_sync, actions)
