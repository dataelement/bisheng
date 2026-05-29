import json
from typing import Generic, TypeVar, Union, Any, List, Optional

from pydantic import BaseModel

DataT = TypeVar('DataT')


class UnifiedResponseModel(BaseModel, Generic[DataT]):
    """Unified Response Model"""
    status_code: int
    status_message: str
    data: DataT = None


def resp_200(data: Union[list, dict, str, Any] = None,
             message: str = 'SUCCESS') -> UnifiedResponseModel:
    """Success code"""
    return UnifiedResponseModel(status_code=200, status_message=message, data=data)
    # return data


def resp_500(code: int = 500,
             data: Union[list, dict, str, Any] = None,
             message: str = 'BAD REQUEST') -> UnifiedResponseModel:
    """Wrong logical response"""
    return UnifiedResponseModel(status_code=code, status_message=message, data=data)


# Obsolete paging data model, old data compatible retention
class PageList(BaseModel, Generic[DataT]):
    list: List[DataT]
    total: int


# Paging Data Model, Use this uniformly in the future
class PageData(BaseModel, Generic[DataT]):
    data: List[DataT]
    total: int


# Cursor-based infinite-scroll envelope for ReBAC list APIs (F027).
# Use this instead of PageData[T] when you want to skip the `total` count
# (and the associated ReBAC scan to compute it) — e.g. high-traffic lists
# where the user only ever scrolls forward.
#
# Frontend usage: pass `next_cursor` from the last page as the next request's
# `cursor` query param; stop loading when `has_more` is False.
class PageInfiniteCursorData(BaseModel, Generic[DataT]):
    data: List[DataT]
    page_size: int
    has_more: bool
    next_cursor: Optional[str] = None


class SSEResponse(BaseModel):
    event: str = "message"
    data: Any

    def to_string(self):
        data = self.data
        if isinstance(self.data, dict):
            data = json.dumps(data)
        elif isinstance(self.data, BaseModel):
            data = json.dumps(self.data.model_dump(mode="json"))

        return f'event: {self.event}\ndata: {data}\n\n'


def resp_501(code: int = 501,
             data: Union[list, dict, str, Any] = None,
             message: str = 'BAD REQUEST') -> UnifiedResponseModel:
    """Wrong logical response"""
    return UnifiedResponseModel(status_code=code, status_message=message, data=data)


def resp_502(code: int = 502,
             data: Union[list, dict, str, Any] = None,
             message: str = 'BAD REQUEST') -> UnifiedResponseModel:
    """Wrong logical response"""
    return UnifiedResponseModel(status_code=code, status_message=message, data=data)
