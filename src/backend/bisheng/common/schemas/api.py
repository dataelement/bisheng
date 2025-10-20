from typing import Generic, TypeVar, Union, Any

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
