from typing import Any

from .base import BaseMidTable, BaseRecord
from .user_engagement_shared import (
    METRIC_SOURCE_FIELD_MAPPING,
    METRIC_SOURCE_INCREMENT,
    USER_ENGAGEMENT_ES_INDEX,
)


class UserIncrementRecord(BaseRecord):
    metric_source: str = METRIC_SOURCE_INCREMENT


class UserIncrement(BaseMidTable):
    _index_name: str = USER_ENGAGEMENT_ES_INDEX
    _mappings: dict[str, Any] = dict(METRIC_SOURCE_FIELD_MAPPING)
    _update_mappings_on_existing: bool = True
    _watermark_filter: dict[str, Any] = {"term": {"metric_source": METRIC_SOURCE_INCREMENT}}
