import json
from typing import Any


def convert_data_type_no_error(v: Any, data_type: Any) -> Any:
    try:
        return data_type(v)
    except Exception as e:
        return v


def convert_openapi_field_value(v: Any, field_type: str) -> Any:
    """ Convert field value based on OpenAPI schema type."""
    v_type = type(v)
    if field_type == 'number' and v_type != float:
        return convert_data_type_no_error(v, float)
    elif field_type == 'integer' and v_type != int:
        return convert_data_type_no_error(v, int)
    elif field_type == 'boolean' and v_type != bool:
        return str(v).strip().lower() == 'true'
    elif field_type == 'string' and v_type != str:
        return convert_data_type_no_error(v, str)
    elif field_type == 'array' and v_type != list:
        return convert_data_type_no_error(v, json.loads)
    elif field_type in ['object', 'dict'] and v_type != dict:
        return convert_data_type_no_error(v, json.loads)
    return v
