from typing import Generic, TypeVar, Union, Any, List

from pydantic import BaseModel

DataT = TypeVar('DataT')


class UnifiedResponseModel(BaseModel, Generic[DataT]):
    """统一响应模型"""
    status_code: int
    status_message: str
    data: DataT = None


def resp_200(data: Union[list, dict, str, Any] = None,
             message: str = 'SUCCESS') -> UnifiedResponseModel:
    """成功的代码"""
    return UnifiedResponseModel(status_code=200, status_message=message, data=data)
    # return data


def resp_500(code: int = 500,
             data: Union[list, dict, str, Any] = None,
             message: str = 'BAD REQUEST') -> UnifiedResponseModel:
    """错误的逻辑回复"""
    return UnifiedResponseModel(status_code=code, status_message=message, data=data)


# 废弃的分页数据模型，旧数据兼容保留
class PageList(BaseModel, Generic[DataT]):
    list: List[DataT]
    total: int


# 分页数据模型, 后续统一用这个
class PageData(BaseModel, Generic[DataT]):
    data: List[DataT]
    total: int


def resp_501(code: int = 501,
             data: Union[list, dict, str, Any] = None,
             message: str = 'BAD REQUEST') -> UnifiedResponseModel:
    """错误的逻辑回复"""
    return UnifiedResponseModel(status_code=code, status_message=message, data=data)


def resp_502(code: int = 502,
             data: Union[list, dict, str, Any] = None,
             message: str = 'BAD REQUEST') -> UnifiedResponseModel:
    """错误的逻辑回复"""
    return UnifiedResponseModel(status_code=code, status_message=message, data=data)
