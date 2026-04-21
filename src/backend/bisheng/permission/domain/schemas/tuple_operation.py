"""Shared TupleOperation DTO for OpenFGA integration.

Used by DepartmentChangeHandler, GroupChangeHandler, and PermissionService.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class TupleOperation:
    """A single OpenFGA tuple write or delete operation.

    Attributes:
        action: 'write' to create a relationship, 'delete' to remove it.
        user: The subject, e.g. "user:7" or "department:5#member".
        relation: The relationship type, e.g. "member", "admin", "owner".
        object: The target, e.g. "department:5", "workflow:abc-123".
    """
    action: Literal['write', 'delete']
    user: str
    relation: str
    object: str
