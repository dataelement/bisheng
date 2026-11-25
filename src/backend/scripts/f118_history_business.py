"""Compatibility import for the original F118 maintenance helper."""

import sys

from bisheng.knowledge.domain.repositories import unification_history_business as _implementation

sys.modules[__name__] = _implementation
