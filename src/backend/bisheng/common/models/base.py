from typing import Dict, Any

from pydantic import ConfigDict
from sqlmodel import SQLModel


class SQLModelSerializable(SQLModel):
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def create_new(cls, **data) -> "SQLModelSerializable":
        """ create a new instance """
        return cls(**data)

    def model_dump(self, **kwargs) -> Dict[str, Any]:
        """ default return mode is json """
        if 'mode' not in kwargs:
            kwargs['mode'] = 'json'
        return super().model_dump(**kwargs)
