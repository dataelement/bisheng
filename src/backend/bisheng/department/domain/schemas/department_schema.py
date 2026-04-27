"""Pydantic DTOs for Department API requests and responses.

Part of F002-department-tree.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class DepartmentMemberAffiliateRolesPayload(BaseModel):
    """兼职部门行：按部门外部 id 提交角色 id 列表。"""

    dept_id: str = Field(..., min_length=1)
    role_ids: List[int] = Field(default_factory=list)


class DepartmentMemberEditApply(BaseModel):
    """组织与成员 · 编辑人员（PRD 3.2.2）提交体。"""

    user_name: Optional[str] = Field(None, max_length=128)
    primary_department_id: Optional[int] = Field(
        None,
        description='主部门 Department.id；仅本地主属可改，须在操作者管辖组织子树内',
    )
    group_ids: Optional[List[int]] = None
    # 兼职人员：仅当前上下文部门角色
    context_role_ids: Optional[List[int]] = None
    # 主属（本地/第三方）：主部门角色 + 各附属部门角色
    primary_role_ids: Optional[List[int]] = None
    affiliate_roles: Optional[List[DepartmentMemberAffiliateRolesPayload]] = None


class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    parent_id: int
    sort_order: int = 0
    default_role_ids: Optional[List[int]] = None
    admin_user_ids: Optional[List[int]] = None


class DepartmentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=50)
    sort_order: Optional[int] = None
    default_role_ids: Optional[List[int]] = None
    #: 与名称、默认角色一并提交时全量替换部门管理员（OpenFGA）；不传则不改管理员
    admin_user_ids: Optional[List[int]] = None
    #: 为 True 时，将当前请求中的默认角色（若未传 ``default_role_ids`` 则用库中已有值）授予本部门全部现存成员
    apply_default_roles_to_existing_members: bool = False


class DepartmentMoveRequest(BaseModel):
    new_parent_id: int


class DepartmentAdminSet(BaseModel):
    """全量替换部门管理员；允许空列表表示清空。"""
    user_ids: List[int] = Field(default_factory=list)


class DepartmentMemberAdd(BaseModel):
    user_ids: List[int] = Field(..., min_length=1)
    is_primary: int = 0


class DepartmentLocalMemberCreate(BaseModel):
    """PRD §3.2.1：在部门内创建本地人员（主部门固定为当前部门）。"""

    user_name: str = Field(..., min_length=1, max_length=128)
    person_id: str = Field(..., min_length=1, max_length=128, description='人员ID（登录唯一凭证）')
    password: str = Field(..., description='RSA 加密后的密码（与 /user/create 一致）')
    role_ids: List[int] = Field(
        default_factory=list,
        description='可选；与部门「默认角色」合并后写入，均须落在当前部门可分配角色内',
    )


class DepartmentLocalMemberCreateWithDeptId(DepartmentLocalMemberCreate):
    """与 ``POST .../local-members`` 等价，但 ``dept_id`` 放在 body，避免路径中的 ``@`` 被网关误解析导致 404。"""

    dept_id: str = Field(..., min_length=1, description='部门外部 id，如 BS@hex')


class DepartmentTreeNode(BaseModel):
    id: int
    dept_id: str
    name: str
    parent_id: Optional[int] = None
    path: str
    sort_order: int = 0
    source: str = 'local'
    status: str = 'active'
    member_count: int = 0
    # F011 mount-state surfaced to the frontend so DepartmentSettings can
    # toggle the "mark as Child Tenant" / "unmount" button, and DepartmentTree
    # can badge mounted nodes. mounted_tenant_id is None when is_tenant_root
    # is False; the backend keeps them in lockstep (see _set_mount_state in
    # DepartmentDao.aset_mount).
    is_tenant_root: bool = False
    mounted_tenant_id: Optional[int] = None
    children: List[DepartmentTreeNode] = []
