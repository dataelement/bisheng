"""Standard DTOs for data fetched from third-party org providers."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RemoteDepartmentDTO:
    """A department fetched from a third-party provider."""
    external_id: str
    name: str
    parent_external_id: Optional[str] = None  # None = root
    sort_order: int = 0


@dataclass
class RemoteMemberDTO:
    """An employee fetched from a third-party provider."""
    external_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    primary_dept_external_id: str = ''
    secondary_dept_external_ids: list[str] = field(default_factory=list)
    status: str = 'active'  # active / disabled
