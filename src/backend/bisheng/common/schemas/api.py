from typing import Generic, TypeVar, Union, Any, List

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
