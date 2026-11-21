from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from bisheng.sensitive_word.domain.schemas import SensitiveWordCheckResult


class ContentSafetyViolation(Exception):
    def __init__(self, result: SensitiveWordCheckResult, documents: Sequence[Any] | None = None) -> None:
        self.result = result
        # The documents that were checked. Callers may segment them for the
        # file detail view; they must not be written to the retrieval index.
        self.documents = list(documents or [])
        super().__init__(result.auto_reply or "content safety violation")

    def to_remark(self) -> dict[str, Any]:
        return {
            "reason": "sensitive_check",
            "auto_reply": self.result.auto_reply,
            "hits": [hit.model_dump() for hit in self.result.hits],
        }
