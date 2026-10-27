"""Bounded, business-independent normalization of saved-tool results."""

import json

from bisheng.common.errcode.dsh import DshToolOutputTooLargeError, DshToolResultInvalidError
from bisheng.utils.bounded_json import check_tree, strict_json


def normalize_result(raw, max_bytes):
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
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > max_bytes:
            raise DshToolOutputTooLargeError()
        return value
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise DshToolResultInvalidError() from None
