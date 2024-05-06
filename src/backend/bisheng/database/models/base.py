from datetime import datetime
from uuid import UUID

import orjson
from sqlmodel import SQLModel


def orjson_dumps(v, *, default=None, sort_keys=False, indent_2=True):
    option = orjson.OPT_SORT_KEYS if sort_keys else None
    if indent_2:
        # orjson.dumps returns bytes, to match standard json.dumps we need to decode
        # option
        # To modify how data is serialized, specify option. Each option is an integer constant in orjson.
        # To specify multiple options, mask them together, e.g., option=orjson.OPT_STRICT_INTEGER | orjson.OPT_NAIVE_UTC
        if option is None:
            option = orjson.OPT_INDENT_2
        else:
            option |= orjson.OPT_INDENT_2
    if default is None:
        return orjson.dumps(v, option=option).decode()
    return orjson.dumps(v, default=default, option=option).decode()


class SQLModelSerializable(SQLModel):

    class Config:
        orm_mode = True
        json_loads = orjson.loads
        json_dumps = orjson_dumps

    def to_dict(self):
        result = self.model_dump()
        for column in result:
            value = getattr(self, column)
            if isinstance(value, datetime):
                # 将datetime对象转换为字符串
                value = value.isoformat()
            elif isinstance(value, UUID):
                # 将UUID对象转换为字符串
                value = value.hex
            result[column] = value
        return result
