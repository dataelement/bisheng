"""Streaming full-buffer content-safety scanner for workbench daily chat."""

from __future__ import annotations

from bisheng.sensitive_word.domain.schemas import (
    SensitiveWordBusinessType,
    SensitiveWordCheckResult,
)
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import (
    SensitiveWordPolicyService,
)

CHECK_INTERVAL = 100


class StreamContentSafetyScanner:
    """Accumulate final-answer deltas and re-check the full buffer every 100 chars.

    Character count uses ``len(str)`` (Unicode code points). Thinking / tool
    text must never be fed here — callers only pass the final answer delta.
    """

    def __init__(self, tenant_id: int) -> None:
        self.tenant_id = tenant_id
        self._buffer = ""
        self._last_checked = 0
        self._hit: SensitiveWordCheckResult | None = None

    def feed(self, delta: str) -> SensitiveWordCheckResult | None:
        if self._hit is not None:
            return self._hit
        if not delta:
            return None
        self._buffer += str(delta)
        if len(self._buffer) - self._last_checked < CHECK_INTERVAL:
            return None
        return self._scan()

    def finish(self) -> SensitiveWordCheckResult | None:
        if self._hit is not None:
            return self._hit
        if not self._buffer or len(self._buffer) == self._last_checked:
            return None
        return self._scan()

    def _scan(self) -> SensitiveWordCheckResult | None:
        result = SensitiveWordPolicyService.check_text(
            tenant_id=self.tenant_id,
            business_type=SensitiveWordBusinessType.WORKBENCH_CHAT,
            text=self._buffer,
        )
        self._last_checked = len(self._buffer)
        if result.enabled and result.hits:
            self._hit = result
            return result
        return None
