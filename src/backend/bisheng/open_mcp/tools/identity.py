"""Identity and organisation MCP tool handlers (`identity:read`).

Answers are tenant-wide and cannot be narrowed: that is the scope's whole
contract (AC-31). "Not in this tenant" and "does not exist" give the same
refusal (AC-32), so a key cannot enumerate other tenants' user ids by watching
which lookups come back differently.
"""

from __future__ import annotations

from bisheng.common.errcode.mcp_face import McpIdentityNotFoundError
from bisheng.department.domain.services.org_directory_service import OrgDirectoryService
from bisheng.open_mcp.contracts import (
    DepartmentMembersResult,
    DeptMembersInput,
    IdentityGetUserInput,
    IdentityUser,
    OrgTreeInput,
    OrgTreeResult,
)


async def identity_get_user(arguments: IdentityGetUserInput) -> IdentityUser:
    """Look up one person's identity and organisational membership by user id."""

    payload = await OrgDirectoryService.aget_user(arguments.target_user_id)
    if payload is None:
        raise McpIdentityNotFoundError()
    return IdentityUser(**payload)


async def org_tree(_arguments: OrgTreeInput) -> OrgTreeResult:
    """Return this tenant's full department tree."""

    return OrgTreeResult(departments=await OrgDirectoryService.atree())


async def dept_members(arguments: DeptMembersInput) -> DepartmentMembersResult:
    """List the members of one department, one page at a time."""

    payload = await OrgDirectoryService.amembers(
        arguments.dept_id,
        page=arguments.page,
        size=arguments.size,
        keyword=arguments.keyword,
    )
    if payload is None:
        raise McpIdentityNotFoundError()
    return DepartmentMembersResult(**payload)


IDENTITY_HANDLERS = {
    "bisheng_identity_get_user": identity_get_user,
    "bisheng_org_tree": org_tree,
    "bisheng_dept_members": dept_members,
}


__all__ = ["IDENTITY_HANDLERS"]
