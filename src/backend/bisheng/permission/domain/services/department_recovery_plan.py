"""Pure, deliberately narrow rules for recovering a frozen department MOVE."""

from __future__ import annotations

import json
from hashlib import sha256


class RecoveryBlockedError(RuntimeError):
    """A local recovery invariant is not satisfied."""


class RecoveryRuntimeError(RuntimeError):
    """The environment cannot safely continue a recovery batch."""


def checksum(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
