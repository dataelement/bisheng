from typing import Generic, List, TypeVar

from pydantic import BaseModel

# 创建泛型变量
DataT = TypeVar('DataT')


class PageList(Generic[DataT], BaseModel):
    list: List[DataT]
    total: int
