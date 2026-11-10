"""Standard DTOs for data fetched from third-party org providers."""

from dataclasses import dataclass, field


@dataclass
class RemoteDepartmentDTO:
    """A department fetched from a third-party provider."""

    external_id: str
    name: str
    parent_external_id: str | None = None  # None = root
    sort_order: int = 0


@dataclass
class RemoteMemberDTO:
    """An employee fetched from a third-party provider."""

    external_id: str
    name: str
    email: str | None = None
    phone: str | None = None
    primary_dept_external_id: str = ""
    secondary_dept_external_ids: list[str] = field(default_factory=list)
    # Departments this member leads (WeCom ``is_leader_in_dept``); pushed as
    # ``department_admin_external_ids`` so department-admin grants track upstream.
    admin_dept_external_ids: list[str] = field(default_factory=list)
    status: str = "active"  # active / disabled
