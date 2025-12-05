from typing import Dict, Any

from .base import BaseMidTable, BaseRecord


class UserIncrementRecord(BaseRecord):
    pass


class UserIncrement(BaseMidTable):
    _index_name: str = 'mid_user_increment'
    _mappings: Dict[str, Any] = {}
