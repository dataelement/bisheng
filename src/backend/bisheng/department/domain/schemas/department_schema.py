"""Pydantic DTOs for Department API requests and responses.

Part of F002-department-tree.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    parent_id: int
    sort_order: int = 0
    default_role_ids: Optional[List[int]] = None


class DepartmentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=50)
    sort_order: Optional[int] = None
    default_role_ids: Optional[List[int]] = None


class DepartmentMoveRequest(BaseModel):
    new_parent_id: int


class DepartmentMemberAdd(BaseModel):
    user_ids: List[int] = Field(..., min_length=1)
    is_primary: int = 0


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
    children: List[DepartmentTreeNode] = []
