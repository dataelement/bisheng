"""Generic normalization and the reserved search business result contract."""

import json
from urllib.parse import urlsplit

from bisheng.common.errcode.dsh import DshToolOutputTooLargeError, DshToolResultInvalidError
from bisheng.utils.bounded_json import check_tree, strict_json


def _string(value, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("Invalid string")


def _search(value, max_results):
    if not isinstance(value, dict) or set(value) - {"output", "results", "truncated"}:
        raise ValueError("Invalid search object")
    if type(value.get("truncated")) is not bool or not isinstance(value.get("results"), list):
        raise ValueError("Invalid search fields")
    if "output" in value:
        _string(value["output"], 65536)
    for row in value["results"]:
        if not isinstance(row, dict) or set(row) - {"url", "title", "snippet", "published_at"}:
            raise ValueError("Invalid search row")
        url = row.get("url")
        _string(url, 8192)
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "\\" in url
            or any(c.isspace() or ord(c) < 32 for c in url)
        ):
            raise ValueError("Invalid search URL")
        _ = parsed.port
        for key, limit in (("title", 4096), ("snippet", 16384), ("published_at", 128)):
            if key in row:
                _string(row[key], limit)
    return {
        **value,
        "results": value["results"][:max_results],
        "truncated": value["truncated"] or len(value["results"]) > max_results,
    }


def normalize_result(tool_code, raw, max_bytes, max_results=20):
    try:
        if isinstance(raw, str):
            if len(raw.encode("utf-8")) > max_bytes:
                raise DshToolOutputTooLargeError()
            try:
                value = strict_json(raw)
            except json.JSONDecodeError:
                value = {"text": raw}
        else:
            value = raw
            check_tree(value)
        if tool_code == "bs_web_search":
            value = _search(value, max_results)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > max_bytes:
            raise DshToolOutputTooLargeError()
        return value
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise DshToolResultInvalidError() from None
