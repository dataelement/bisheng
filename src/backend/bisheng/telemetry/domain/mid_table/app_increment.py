from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.telemetry.domain.mid_table.base import BaseMidTable, BaseRecord


class AppIncrementRecord(BaseRecord):
    app_id: str
    app_name: str
    app_type: ApplicationTypeEnum


class AppIncrement(BaseMidTable):
    _index_name = 'mid_app_increment'
    _mappings = {
        "app_id": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "app_name": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "app_type": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
    }
