"""F048 permission-notification candidate adapter.

The adapter consumes normalized assignee provenance supplied by the Grant
application service. It does not inspect relation bindings, query resources, or
make permission decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PermissionGrantNotificationItem:
    operation: str
    subject_type: str
    subject_id: str
    include_children: bool
    source_type: str
    model_key: str
    action_codes: tuple[str, ...]


class PermissionNotificationSubjectPort(Protocol):
    async def resolve_user_ids(
        self,
        subject_type: str,
        subject_id: str,
        include_children: bool,
    ) -> frozenset[int]: ...


@dataclass
class ResourcePermissionNotificationContext:
    resource_type: str
    resource_id: str
    grant_user_ids: set[int] = field(default_factory=set)
    revoke_user_ids: set[int] = field(default_factory=set)
    read_revoke_user_ids: set[int] = field(default_factory=set)

    @property
    def has_events(self) -> bool:
        return bool(
            self.grant_user_ids
            or self.revoke_user_ids
            or self.read_revoke_user_ids
        )


class F048PermissionNotificationAdapter:
    """Derive notification candidates from normalized Grant facts."""

    def __init__(self, *, subjects: PermissionNotificationSubjectPort) -> None:
        self._subjects = subjects

    async def build_context(
        self,
        *,
        resource_type: str,
        resource_id: str,
        changes: tuple[PermissionGrantNotificationItem, ...],
    ) -> ResourcePermissionNotificationContext:
        context = ResourcePermissionNotificationContext(
            resource_type=resource_type,
            resource_id=resource_id,
        )
        for change in changes:
            operation = change.operation.upper()
            if (
                operation not in {"ADD", "REMOVE"}
                or not change.source_type
                or not change.model_key
                or not change.action_codes
            ):
                raise ValueError(
                    "invalid F048 permission notification change"
                )
            user_ids = set(
                await self._subjects.resolve_user_ids(
                    change.subject_type,
                    change.subject_id,
                    change.include_children,
                )
            )
            if "manage_permission" in change.action_codes:
                if operation == "ADD":
                    context.grant_user_ids.update(user_ids)
                else:
                    context.revoke_user_ids.update(user_ids)
            if operation == "REMOVE":
                context.read_revoke_user_ids.update(user_ids)
        return context
