"""OwnerService — convenience methods for resource ownership management (T13).

Provides the contract for F008 (resource adaptation) to call when creating resources.
INV-2: every resource must have exactly one owner tuple in OpenFGA.
"""

from __future__ import annotations

import logging
from typing import Optional

from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem, AuthorizeRevokeItem

logger = logging.getLogger(__name__)


class OwnerService:
    """Stateless service for owner tuple management. All methods are @classmethod."""

    @classmethod
    async def write_owner_tuple(
        cls,
        user_id: int,
        object_type: str,
        object_id: str,
    ) -> None:
        """Write an owner tuple for a newly created resource.

        Called during resource creation (F008 integration point).
        Does not raise on failure — FailedTuple compensation handles retries.
        """
        from bisheng.permission.domain.services.permission_service import PermissionService
        await PermissionService.authorize(
            object_type=object_type,
            object_id=object_id,
            grants=[
                AuthorizeGrantItem(
                    subject_type='user',
                    subject_id=user_id,
                    relation='owner',
                    include_children=False,
                ),
            ],
        )

    @classmethod
    async def check_is_owner(
        cls,
        user_id: int,
        object_type: str,
        object_id: str,
    ) -> bool:
        """Check if user is the owner of a resource."""
        from bisheng.permission.domain.services.permission_service import PermissionService
        return await PermissionService.check(
            user_id=user_id,
            relation='owner',
            object_type=object_type,
            object_id=object_id,
        )

    @classmethod
    async def transfer_ownership(
        cls,
        from_user_id: int,
        to_user_id: int,
        object_type: str,
        object_id: str,
    ) -> None:
        """Transfer ownership from one user to another.

        Single authorize() call with revoke old + grant new.
        """
        from bisheng.permission.domain.services.permission_service import PermissionService
        await PermissionService.authorize(
            object_type=object_type,
            object_id=object_id,
            grants=[
                AuthorizeGrantItem(
                    subject_type='user',
                    subject_id=to_user_id,
                    relation='owner',
                    include_children=False,
                ),
            ],
            revokes=[
                AuthorizeRevokeItem(
                    subject_type='user',
                    subject_id=from_user_id,
                    relation='owner',
                    include_children=False,
                ),
            ],
        )
