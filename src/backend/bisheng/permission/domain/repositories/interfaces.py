"""Repository ports for the F048 permission control plane."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any

from bisheng.permission.domain.models import (
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionMigrationItem,
    PermissionMigrationRun,
    PermissionProjectionOperation,
    PermissionProjectionTuple,
    ResourcePermissionMode,
)


class PermissionRepositoryTransactionPort(ABC):
    """Shared unit-of-work boundary for multi-row permission mutations."""

    @abstractmethod
    def transaction(self) -> AbstractAsyncContextManager[Any]:
        """Return a transaction-scoped context manager."""


class PermissionCatalogRepositoryPort(PermissionRepositoryTransactionPort):
    @abstractmethod
    async def aget_current_release(
        self,
        *,
        for_update: bool = False,
    ) -> PermissionCatalogRelease | None:
        """Get the unique current release, optionally fenced by a row lock."""

    @abstractmethod
    async def aget_release(self, release_id: int) -> PermissionCatalogRelease | None:
        """Get one Catalog release."""

    @abstractmethod
    async def acreate_release(
        self,
        release: PermissionCatalogRelease,
    ) -> PermissionCatalogRelease:
        """Persist a complete draft release head."""

    @abstractmethod
    async def aupdate_release_cas(
        self,
        *,
        release_id: int,
        expected_version: int,
        values: dict[str, Any],
    ) -> bool:
        """Update a release only when its optimistic version still matches."""

    @abstractmethod
    async def aget_impact_cursor(
        self,
        *,
        after_tenant_id: int | None,
        after_resource_type: str | None,
        after_resource_id: str | None,
        limit: int,
    ) -> tuple[list[tuple[int, str, str]], tuple[int, str, str] | None]:
        """Return a bounded cross-tenant Grant resource cursor."""

    @abstractmethod
    async def aget_release_checksum(self, release_id: int) -> str | None:
        """Return the persisted normalized release checksum."""


class PermissionGrantRepositoryPort(PermissionRepositoryTransactionPort):
    @abstractmethod
    async def aget_grant(
        self,
        *,
        resource_type: str,
        resource_id: str,
        model_key: str,
        for_update: bool = False,
    ) -> PermissionGrant | None:
        """Get one logical Grant in the current tenant."""

    @abstractmethod
    async def acreate_grant(self, grant: PermissionGrant) -> PermissionGrant:
        """Create a stable logical Grant."""

    @abstractmethod
    async def aupdate_grant_cas(
        self,
        *,
        grant_id: int,
        expected_version: int,
        values: dict[str, Any],
    ) -> bool:
        """Update one Grant through optimistic version CAS."""

    @abstractmethod
    async def aget_assignee(
        self,
        assignee_id: int,
        *,
        for_update: bool = False,
    ) -> PermissionGrantAssignee | None:
        """Get one source-specific assignee row."""

    @abstractmethod
    async def acreate_assignee(
        self,
        assignee: PermissionGrantAssignee,
    ) -> PermissionGrantAssignee:
        """Create one normalized assignment source."""

    @abstractmethod
    async def aupdate_assignee_cas(
        self,
        *,
        assignee_id: int,
        expected_version: int,
        values: dict[str, Any],
    ) -> bool:
        """Update one assignee source through optimistic version CAS."""

    @abstractmethod
    async def aget_assignee_cursor(
        self,
        *,
        resource_type: str,
        resource_id: str,
        after_id: int,
        limit: int,
    ) -> tuple[list[PermissionGrantAssignee], int | None]:
        """Return a stable ID cursor without an expensive total count."""

    @abstractmethod
    async def acount_projected_subject_sources(
        self,
        *,
        grant_id: int,
        projected_subject: str,
        protected: bool,
    ) -> int:
        """Count active sources before deleting their shared OpenFGA tuple."""


class ResourcePermissionModeRepositoryPort(PermissionRepositoryTransactionPort):
    @abstractmethod
    async def aget_mode(
        self,
        *,
        resource_type: str,
        resource_id: str,
        for_update: bool = False,
    ) -> ResourcePermissionMode | None:
        """Get the canonical permission mode mirror."""

    @abstractmethod
    async def acreate_mode(
        self,
        mode: ResourcePermissionMode,
    ) -> ResourcePermissionMode:
        """Create a resource permission mode."""

    @abstractmethod
    async def aupdate_mode_cas(
        self,
        *,
        mode_id: int,
        expected_version: int,
        values: dict[str, Any],
    ) -> bool:
        """Update a mode only at the expected resource version."""


class PermissionProjectionRepositoryPort(PermissionRepositoryTransactionPort):
    @abstractmethod
    async def aget_operation(
        self,
        operation_id: int,
    ) -> PermissionProjectionOperation | None:
        """Get one tenant-scoped projection operation by durable ID."""

    @abstractmethod
    async def aget_operation_by_idempotency(
        self,
        idempotency_key: str,
        *,
        for_update: bool = False,
    ) -> PermissionProjectionOperation | None:
        """Get an operation in the current tenant by idempotency key."""

    @abstractmethod
    async def acreate_operation(
        self,
        operation: PermissionProjectionOperation,
        tuples: list[PermissionProjectionTuple],
    ) -> PermissionProjectionOperation:
        """Atomically persist the operation head and normalized tuple delta."""

    @abstractmethod
    async def aupdate_operation_status_cas(
        self,
        *,
        operation_id: int,
        expected_status: str,
        target_status: str,
        commit_checksum: str | None = None,
        error_code: int | None = None,
        error_message: str | None = None,
    ) -> bool:
        """Advance an operation status only from the expected state."""

    @abstractmethod
    async def aget_operation_tuples(
        self,
        operation_id: int,
    ) -> list[PermissionProjectionTuple]:
        """Return tuple rows in canonical phase/sequence order."""

    @abstractmethod
    async def aget_retry_cursor(
        self,
        *,
        statuses: tuple[str, ...],
        updated_before: datetime,
        after_id: int,
        limit: int,
    ) -> tuple[list[PermissionProjectionOperation], int | None]:
        """Return a bounded retry cursor."""

    @abstractmethod
    async def aget_operation_checksum(self, operation_id: int) -> str | None:
        """Return a checksum rebuilt from normalized tuple rows."""


class PermissionMigrationRepositoryPort(PermissionRepositoryTransactionPort):
    @abstractmethod
    async def aget_run(
        self,
        run_id: int,
    ) -> PermissionMigrationRun | None:
        """Load one formal migration run by its durable identifier."""

    @abstractmethod
    async def aget_or_create_run(
        self,
        run: PermissionMigrationRun,
    ) -> PermissionMigrationRun:
        """Resume the unique run for an environment fingerprint."""

    @abstractmethod
    async def aacquire_environment_lease(
        self,
        *,
        run_id: int,
        expected_version: int,
        lock_token: str,
        expires_at: datetime,
    ) -> bool:
        """Acquire or renew the one-run environment lease through CAS."""

    @abstractmethod
    async def aupdate_checkpoint_cas(
        self,
        *,
        run_id: int,
        expected_version: int,
        phase: str,
        checkpoint: str | None,
        source_checksum: str | None,
        target_checksum: str | None,
    ) -> bool:
        """Persist a resumable checkpoint and its checksums."""

    @abstractmethod
    async def abind_target_model_cas(
        self,
        *,
        run_id: int,
        expected_version: int,
        target_model_id: str,
    ) -> bool:
        """Bind the immutable target model once through version CAS."""

    @abstractmethod
    async def aupdate_run_state_cas(
        self,
        *,
        run_id: int,
        expected_version: int,
        phase: str,
        status: str,
        checkpoint: str | None,
        source_checksum: str | None,
        target_checksum: str | None,
        report_checksum: str | None = None,
    ) -> bool:
        """Advance the formal run phase/status through one version CAS."""

    @abstractmethod
    async def aupsert_item(
        self,
        item: PermissionMigrationItem,
    ) -> PermissionMigrationItem:
        """Create or verify one source-locator migration item."""

    @abstractmethod
    async def aupsert_items(
        self,
        items: tuple[PermissionMigrationItem, ...],
    ) -> list[PermissionMigrationItem]:
        """Create or verify one bounded batch of migration items."""

    @abstractmethod
    async def aget_item_cursor(
        self,
        *,
        run_id: int,
        statuses: tuple[str, ...],
        after_id: int,
        limit: int,
    ) -> tuple[list[PermissionMigrationItem], int | None]:
        """Read migration items through the repository's narrow bypass."""

    @abstractmethod
    async def alist_source_items(
        self,
        *,
        run_id: int,
    ) -> list[PermissionMigrationItem]:
        """Load the frozen non-target facts needed for forward-only resume."""

    @abstractmethod
    async def aget_run_checksum(self, run_id: int) -> str | None:
        """Return the deterministic aggregate item checksum."""
