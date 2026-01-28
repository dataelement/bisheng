from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.telemetry.domain.mid_table.base import BaseMidTable, BaseRecord


class UserInteractRecord(BaseRecord):
    message_id: int
    event_id: str
    interact_type: str
    app_id: str
    app_name: str


class UserInteract(BaseMidTable):
    _index_name = 'mid_user_interact_dtl'
    _mappings = {
        "message_id": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "event_id": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "interact_type": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "app_id": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "app_name": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
    }

    def get_records_by_time_range_sync(self, start_time: int, end_time: int, page: int = 1, page_size: int = 1000):
        query = {
            "bool": {
                "filter": [
                    {"term": {"event_type": {"value": BaseTelemetryTypeEnum.MESSAGE_FEEDBACK.value}}},
                    {"range": {"timestamp": {"gte": start_time * 1000, "lt": end_time * 1000}}}
                ]
            }
        }

        return self.search_from_base_sync(body={"query": query, "from": (page - 1) * page_size, "size": page_size})
