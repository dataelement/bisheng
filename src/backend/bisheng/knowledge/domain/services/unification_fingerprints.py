"""Canonical migration fingerprints; hashing values grants no write authority."""

import hashlib
import json
from datetime import datetime
from enum import Enum

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError


def _invalid():
    raise KnowledgeOperationPlanConflictError(reason="migration_inventory_codec_invalid")


def canonical(value):
    def scalar(item):
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, Enum):
            return item.value
        if type(item) in (tuple, set, frozenset):
            return sorted(item) if type(item) in (set, frozenset) else list(item)
        raise TypeError("unsupported inventory scalar")

    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=scalar
        ).encode()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _invalid()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()
