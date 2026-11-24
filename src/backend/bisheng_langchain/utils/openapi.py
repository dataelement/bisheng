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


def _is_null_schema(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    field_type = schema.get('type')
    return field_type == 'null' or field_type == ['null']


def resolve_openapi_type(schema: Any) -> str | None:
    """Return the single concrete JSON type of an OpenAPI schema.

    Handles OpenAPI 3.1 type arrays (``["integer", "null"]``) and ``anyOf``/``oneOf``
    unions. ``null`` members are ignored. Returns None when the schema has no type
    or when its non-null members disagree (e.g. string | array): the caller must
    then treat the value as untyped and must not coerce it.
    """
    if not isinstance(schema, dict):
        return None
    field_type = schema.get('type')
    if isinstance(field_type, str):
        return field_type
    if isinstance(field_type, list):
        concrete = {one for one in field_type if one != 'null'}
        return concrete.pop() if len(concrete) == 1 else None
    for key in ('anyOf', 'oneOf'):
        branches = schema.get(key)
        if isinstance(branches, list):
            concrete = {resolve_openapi_type(one) for one in branches if not _is_null_schema(one)}
            return concrete.pop() if len(concrete) == 1 else None
    return None


def has_null_member(schema: Any) -> bool:
    """True when a 3.1 type array or an anyOf/oneOf union lists null as an allowed type.

    The OpenAPI 3.0 ``nullable`` keyword is not considered here; use ``is_nullable``.
    """
    if not isinstance(schema, dict):
        return False
    field_type = schema.get('type')
    if isinstance(field_type, list) and 'null' in field_type:
        return True
    return any(
        isinstance(schema.get(key), list) and any(_is_null_schema(one) for one in schema[key])
        for key in ('anyOf', 'oneOf')
    )


def is_nullable(schema: Any) -> bool:
    """True when the schema allows null: OpenAPI 3.0 ``nullable: true`` or a null member."""
    if isinstance(schema, dict) and schema.get('nullable') is True:
        return True
    return has_null_member(schema)
