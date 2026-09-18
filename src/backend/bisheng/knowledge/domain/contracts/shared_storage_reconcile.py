"""全量对账的内存快照与差异, 不引入持久化状态。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DocumentSnapshot:
    document_id: int
    version_id: int = 0
    file_id: int = 0
    entry_id: int = 0
    generation: int = 0
    membership_generation: int = 0
    knowledge_ids: tuple[int, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    signature: str = ""
    skip_reason: str = ""
    tenant_id: int = 1

    @property
    def expected_metadata(self) -> dict[str, Any]:
        return {
            **self.metadata,
            "knowledge_ids": list(self.knowledge_ids),
            "knowledge_id": self.knowledge_ids[0],
            "membership_generation": self.membership_generation,
        }


@dataclass(frozen=True)
class MetadataRepair:
    snapshot: DocumentSnapshot
    rows: list[dict[str, Any]]


class ReconcileLockLost(RuntimeError):
    """失去任务所有权时, 不再发起任何写入。"""


class ReconcileQueryError(RuntimeError):
    """查询不完整或超时, 不能将结果解释为空数据。"""
