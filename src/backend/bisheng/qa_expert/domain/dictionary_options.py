"""Normalize expert career dictionary keys for filters and dropdowns."""

from collections.abc import Sequence

CAREER_FIELD_TO_TYPE = {
    "job_family": "expert_job_family",
    "job_category": "expert_job_category",
    "position": "expert_position",
    "major": "expert_major",
}

FILTER_FIELD_TO_TYPE = {
    "job_families": "expert_job_family",
    "job_categories": "expert_job_category",
    "positions": "expert_position",
    "majors": "expert_major",
}


def canonical_dict_options(keys: Sequence[str], dict_items: Sequence[object]) -> list[dict[str, str]]:
    """Collapse stored dict keys and display values into unique filter options."""
    key_to_value: dict[str, str] = {}
    value_to_key: dict[str, str] = {}
    for item in dict_items:
        dict_key = str(getattr(item, "dict_key", "") or "").strip()
        dict_value = str(getattr(item, "dict_value", "") or "").strip()
        if not dict_key:
            continue
        display = dict_value or dict_key
        key_to_value[dict_key] = display
        display_fold = display.casefold()
        if display_fold not in value_to_key:
            value_to_key[display_fold] = dict_key

    seen: set[str] = set()
    options: list[dict[str, str]] = []
    for raw in keys:
        stored = str(raw or "").strip()
        if not stored:
            continue
        if stored in key_to_value:
            dict_key = stored
            dict_value = key_to_value[stored]
        elif stored.casefold() in value_to_key:
            dict_key = value_to_key[stored.casefold()]
            dict_value = key_to_value[dict_key]
        else:
            dict_key = stored
            dict_value = stored
        marker = dict_value.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        options.append({"dict_key": dict_key, "dict_value": dict_value})
    return options


def dict_filter_aliases(value: str, dict_items: Sequence[object]) -> list[str]:
    """Return all stored forms that represent the same dictionary option."""
    trimmed = str(value or "").strip()
    if not trimmed:
        return []
    key_to_value: dict[str, str] = {}
    for item in dict_items:
        dict_key = str(getattr(item, "dict_key", "") or "").strip()
        dict_value = str(getattr(item, "dict_value", "") or "").strip()
        if dict_key:
            key_to_value[dict_key] = dict_value or dict_key

    display = key_to_value.get(trimmed, trimmed)
    aliases = {trimmed, display}
    display_fold = display.casefold()
    for dict_key, dict_value in key_to_value.items():
        if dict_key.casefold() == display_fold or dict_value.casefold() == display_fold:
            aliases.add(dict_key)
            aliases.add(dict_value)
    return sorted(alias for alias in aliases if alias)
