"""Copy-only credential projection for tool list/read responses."""

import json
from copy import deepcopy

MASK = "********"
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "api_secret",
        "password",
        "db_password",
        "secret",
        "secret_key",
        "access_token",
        "authorization",
        "token",
        "client_secret",
    }
)


def _secret_key(key: object) -> bool:
    name = str(key).lower().replace("-", "_")
    return name in _SECRET_KEYS or name.endswith(("_api_key", "_secret", "_password", "_access_key"))


def mask_configuration(value):
    """Handle nested lists and JSON-encoded configs without changing the source."""
    if isinstance(value, dict):
        return {key: MASK if _secret_key(key) and item else mask_configuration(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_configuration(item) for item in value]
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return value
        if isinstance(decoded, dict | list):
            return json.dumps(mask_configuration(decoded), ensure_ascii=False)
    return value


def tool_read_view(model, *, include_configuration: bool):
    """The editor may inspect config shape; use-only callers only need metadata."""
    result = model.model_copy(deep=True)
    result.api_key = MASK if result.api_key else result.api_key
    result.extra = mask_configuration(result.extra) if include_configuration else "{}"
    result.openapi_schema = mask_configuration(result.openapi_schema) if include_configuration else ""
    for child in result.children or []:
        child.extra = mask_configuration(child.extra) if include_configuration else None
    return result


def restore_masked_configuration(submitted, original):
    """Restore masks by exact field/list position, only for recognized secrets."""
    if isinstance(submitted, str) and isinstance(original, str):
        try:
            new_data, old_data = json.loads(submitted), json.loads(original)
        except (ValueError, TypeError):
            return submitted
        if isinstance(new_data, dict | list) and isinstance(old_data, type(new_data)):
            return json.dumps(restore_masked_configuration(new_data, old_data), ensure_ascii=False)
    if isinstance(submitted, dict) and isinstance(original, dict):
        return {
            key: original.get(key)
            if _secret_key(key) and value == MASK and key in original
            else restore_masked_configuration(value, original.get(key))
            for key, value in submitted.items()
        }
    if isinstance(submitted, list) and isinstance(original, list):
        return [
            restore_masked_configuration(value, original[i] if i < len(original) else None)
            for i, value in enumerate(submitted)
        ]
    return submitted


def merge_masked_configuration(original: dict, submitted: dict) -> dict:
    """Merge a partial editor config recursively; lists remain explicit replacements."""
    if not isinstance(original, dict) or not isinstance(submitted, dict):
        raise ValueError("Tool configuration must be an object")
    result = deepcopy(original)
    for key, value in submitted.items():
        old = original.get(key)
        if isinstance(old, dict) and isinstance(value, dict):
            result[key] = merge_masked_configuration(old, value)
        elif _secret_key(key) and value == MASK and key in original:
            result[key] = deepcopy(old)
        else:
            result[key] = restore_masked_configuration(value, old)
    return result


def preserved_api_key(submitted, original):
    """An unchanged masked editor value is not a new credential; empty clears."""
    return original if submitted == MASK else submitted
