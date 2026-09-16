"""门户问答内部契约，不接受客户端策略覆盖。"""

from dataclasses import dataclass, field
from typing import Any
from enum import Enum


class QaRetrievalErrorKind(str, Enum):
    BACKENDS = "backends_unavailable"
    INCOMPLETE = "incomplete_without_candidates"
    SCOPE_CHANGED = "scope_changed"
    DEADLINE = "retrieval_deadline"


class QaRetrievalError(RuntimeError):
    def __init__(self, kind: QaRetrievalErrorKind, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class QaRetrievalPlan:
    space_ids: tuple[int, ...]
    # None 是整库；空映射是明确没有获准文件。
    file_ids_by_space: dict[int, list[int]] | None = None


@dataclass
class QaRetrievalResult:
    hits: list[Any] = field(default_factory=list)
    raw_hits: dict[tuple[int, int, int], Any] = field(default_factory=dict)
    scope_complete: bool = True
    degraded_reasons: list[str] = field(default_factory=list)
    rounds: int = 0

    @property
    def status(self) -> str:
        if not self.scope_complete or self.degraded_reasons:
            return 'partial'
        return 'ok' if self.hits else 'empty'


def canonical_key(hit) -> tuple[int, int, int]:
    return (int(hit.canonical_document_id), int(hit.canonical_version_id), int(hit.chunk_index))


def unified_qa_enabled(config, user) -> bool:
    return (
        config.portal_unified_qa_enabled is True
        and int(user.tenant_id) in config.portal_unified_qa_tenant_ids
        and (not config.portal_unified_qa_user_ids or int(user.user_id) in config.portal_unified_qa_user_ids)
    )
