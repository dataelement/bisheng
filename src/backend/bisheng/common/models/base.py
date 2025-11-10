from typing import Union, Dict, Any

from pydantic import ConfigDict
from sqlmodel import SQLModel
from sqlmodel.main import IncEx
from typing_extensions import Literal


class SQLModelSerializable(SQLModel):
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def create_new(cls, **data) -> "SQLModelSerializable":
        """ create a new instance """
        return cls(**data)

    def model_dump(
            self,
            *,
            mode: Union[Literal["json", "python"], str] = "json",
            include: IncEx = None,
            exclude: IncEx = None,
            by_alias: bool = False,
            exclude_unset: bool = False,
            exclude_defaults: bool = False,
            exclude_none: bool = False,
            round_trip: bool = False,
            warnings: bool = True,
    ) -> Dict[str, Any]:
        """ default return mode is json """
        return super().model_dump(
            mode=mode,
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            round_trip=round_trip,
            warnings=warnings)
