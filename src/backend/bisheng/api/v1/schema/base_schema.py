from typing import Generic, List, TypeVar

from pydantic import BaseModel

# Create generic variables
DataT = TypeVar('DataT')


class PageList(BaseModel, Generic[DataT]):
    list: List[DataT]
    total: int
