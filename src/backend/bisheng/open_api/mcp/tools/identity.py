"""Category ④ — identity and organisation lookup (`identity:read`).

Answers are tenant-wide and cannot be narrowed: that is the scope's whole
contract (AC-31). "Not in this tenant" and "does not exist" give the same
refusal (AC-32), so a key cannot enumerate other tenants' user ids by watching
which lookups come back differently.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from bisheng.common.errcode.mcp_face import McpIdentityNotFoundError
from bisheng.department.domain.services.org_directory_service import (
    MAX_MEMBER_PAGE_SIZE,
    OrgDirectoryService,
)


class DepartmentRef(BaseModel):
    dept_id: str
    name: str
    path: str


class IdentityUser(BaseModel):
    user_id: int
    user_name: str
    status: str
    departments: list[DepartmentRef] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)


class DepartmentNode(BaseModel):
    dept_id: str
    name: str
    parent_id: str | None = None
    path: str
    sort_order: int = 0
    source: str = "local"
    status: str = "active"
    children: list[DepartmentNode] = Field(default_factory=list)


DepartmentNode.model_rebuild()


class OrgTreeResult(BaseModel):
    departments: list[DepartmentNode] = Field(default_factory=list)


class DepartmentMember(BaseModel):
    user_id: int
    user_name: str
    status: str


class DepartmentMembersResult(BaseModel):
    members: list[DepartmentMember] = Field(default_factory=list)
    total: int = 0


async def bisheng_identity_get_user(user_id: int) -> IdentityUser:
    """Look up one person's identity and organisational membership by user id."""

    payload = await OrgDirectoryService.aget_user(int(user_id))
    if payload is None:
        raise McpIdentityNotFoundError()
    return IdentityUser(**payload)


async def bisheng_org_tree() -> OrgTreeResult:
    """Return this tenant's full department tree."""

    return OrgTreeResult(departments=await OrgDirectoryService.atree())


async def bisheng_dept_members(
    dept_id: str,
    page: int = 1,
    size: int = 50,
    keyword: str | None = None,
) -> DepartmentMembersResult:
    """List the members of one department, one page at a time."""

    payload = await OrgDirectoryService.amembers(
        str(dept_id),
        page=int(page or 1),
        size=min(int(size or 50), MAX_MEMBER_PAGE_SIZE),
        keyword=keyword,
    )
    if payload is None:
        raise McpIdentityNotFoundError()
    return DepartmentMembersResult(**payload)


__all__ = [
    "bisheng_dept_members",
    "bisheng_identity_get_user",
    "bisheng_org_tree",
]
