from __future__ import annotations

from enum import Enum


class KnowledgeParsePriority(str, Enum):
    """Stable business priority for knowledge file parsing."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {
            self.HIGH: 3,
            self.MEDIUM: 2,
            self.LOW: 1,
        }[self]

    @property
    def celery_priority(self) -> int:
        return {
            self.HIGH: 0,
            self.MEDIUM: 3,
            self.LOW: 9,
        }[self]

    @classmethod
    def parse(
        cls,
        value: object,
        *,
        default: KnowledgeParsePriority | None = None,
    ) -> KnowledgeParsePriority:
        if value is None and default is not None:
            return default
        try:
            return cls(value)
        except (TypeError, ValueError):
            if default is not None:
                return default
            raise


KNOWLEDGE_PARSE_PRIORITY_CONFIG_KEY = "knowledge_file_parse_priority"
KNOWLEDGE_PARSE_PRIORITY_STEPS = (0, 3, 6, 9)
