from __future__ import annotations

from typing import Any, Dict

from bisheng.sensitive_word.domain.schemas import SensitiveWordCheckResult


class ContentSafetyViolation(Exception):
    def __init__(self, result: SensitiveWordCheckResult) -> None:
        self.result = result
        super().__init__(result.auto_reply or 'content safety violation')

    def to_remark(self) -> Dict[str, Any]:
        return {
            'reason': 'sensitive_check',
            'auto_reply': self.result.auto_reply,
            'hits': [hit.model_dump() for hit in self.result.hits],
        }
