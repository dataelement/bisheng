"""Strict facade over MIG/INT-owned persisted reference coverage protocols.

The ledger adapters receive the business Session from the composition root;
this module never imports a knowledge model, opens a Session or guesses that a
tenant with no returned references is covered.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.resource_reference.application.contracts import (
    CoveragePort,
    CoverageStatus,
    GlobalCoveragePort,
    GlobalCoverageStatus,
    SourceType,
    TransactionIdentity,
    tenant_inventory_digest,
)
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


class CoverageRepository:
    def __init__(
        self,
        port: CoveragePort,
        *,
        writer_contract_version: str = "f118-v1",
        global_port: GlobalCoveragePort | None = None,
        initializer=None,
    ):
        if not writer_contract_version or len(writer_contract_version) > 64:
            raise ValueError("a stable writer contract version is required")
        self.port = port
        self.writer_contract_version = writer_contract_version
        self.global_port = global_port
        self.initializer = initializer

    @staticmethod
    def _tenant(tenant_id=None) -> int:
        try:
            trusted = ReferenceRepository.current_tenant_id()
        except Exception as exc:
            raise ReferenceCoverageNotReadyError(reason="coverage_tenant_scope_invalid") from exc
        if tenant_id is not None and (isinstance(tenant_id, bool) or tenant_id != trusted):
            raise ReferenceCoverageNotReadyError(reason="coverage_tenant_scope_invalid")
        return trusted

    def _validate_status(self, status, tenant_id, source_type):
        if (
            not isinstance(status, CoverageStatus)
            or status.ready is not True
            or status.tenant_id != tenant_id
            or status.source_type != source_type
            or status.writer_contract_version != self.writer_contract_version
        ):
            raise ReferenceCoverageNotReadyError(reason="coverage_incomplete")
        return status

    def require_ready(self, *, tenant_id: int | None = None) -> tuple[CoverageStatus, ...]:
        tenant_id = self._tenant(tenant_id)
        statuses = []
        for source_type in SourceType:
            try:
                status = self.port.get_status(tenant_id, source_type, self.writer_contract_version)
            except ReferenceCoverageNotReadyError:
                raise
            except Exception as exc:
                raise ReferenceCoverageNotReadyError(reason="coverage_check_failed") from exc
            statuses.append(self._validate_status(status, tenant_id, source_type))
        return tuple(statuses)

    async def arequire_ready(self, *, tenant_id: int | None = None) -> tuple[CoverageStatus, ...]:
        tenant_id = self._tenant(tenant_id)
        statuses = []
        for source_type in SourceType:
            try:
                status = await self.port.aget_status(tenant_id, source_type, self.writer_contract_version)
            except ReferenceCoverageNotReadyError:
                raise
            except Exception as exc:
                raise ReferenceCoverageNotReadyError(reason="coverage_check_failed") from exc
            statuses.append(self._validate_status(status, tenant_id, source_type))
        return tuple(statuses)

    def _validate_global(self, status, observed_source_tenant_ids, expected_epoch, expected_inventory_hash):
        if (
            not isinstance(status, GlobalCoverageStatus)
            or status.ready is not True
            or status.writer_contract_version != self.writer_contract_version
            or len(status.source_types) != len(SourceType)
            or set(status.source_types) != set(SourceType)
            or not status.verified_tenant_ids
            or status.coverage_epoch <= 0
            or status.tenant_inventory_hash != tenant_inventory_digest(status.verified_tenant_ids)
        ):
            raise ReferenceCoverageNotReadyError(reason="global_coverage_incomplete")
        if expected_epoch is not None and (
            isinstance(expected_epoch, bool)
            or not isinstance(expected_epoch, int)
            or expected_epoch != status.coverage_epoch
        ):
            raise ReferenceCoverageNotReadyError(reason="global_coverage_changed")
        if expected_inventory_hash is not None and expected_inventory_hash != status.tenant_inventory_hash:
            raise ReferenceCoverageNotReadyError(reason="global_coverage_changed")
        if any(
            isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id not in status.verified_tenant_ids
            for tenant_id in observed_source_tenant_ids
        ):
            raise ReferenceCoverageNotReadyError(reason="global_source_tenant_unverified")
        return status

    def require_global_ready(
        self,
        *,
        observed_source_tenant_ids: tuple[int, ...] = (),
        expected_epoch: int | None = None,
        expected_inventory_hash: str | None = None,
    ) -> GlobalCoverageStatus:
        self._tenant()
        if self.global_port is None:
            raise ReferenceCoverageNotReadyError(reason="global_coverage_port_missing")
        try:
            status = self.global_port.get_global_status(self.writer_contract_version)
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as exc:
            raise ReferenceCoverageNotReadyError(reason="global_coverage_check_failed") from exc
        return self._validate_global(status, observed_source_tenant_ids, expected_epoch, expected_inventory_hash)

    async def arequire_global_ready(
        self,
        *,
        observed_source_tenant_ids: tuple[int, ...] = (),
        expected_epoch: int | None = None,
        expected_inventory_hash: str | None = None,
    ) -> GlobalCoverageStatus:
        self._tenant()
        if self.global_port is None:
            raise ReferenceCoverageNotReadyError(reason="global_coverage_port_missing")
        try:
            status = await self.global_port.aget_global_status(self.writer_contract_version)
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as exc:
            raise ReferenceCoverageNotReadyError(reason="global_coverage_check_failed") from exc
        return self._validate_global(status, observed_source_tenant_ids, expected_epoch, expected_inventory_hash)

    def _initialization_context(self, session, tenant_id, writer_contract_version):
        self._tenant(tenant_id)
        if self.initializer is None or writer_contract_version != self.writer_contract_version:
            raise ReferenceCoverageNotReadyError(reason="coverage_initialization_unavailable")
        try:
            return TransactionIdentity.capture(session)
        except (TypeError, ValueError) as exc:
            raise ReferenceCoverageNotReadyError(reason="coverage_initialization_requires_transaction") from exc

    def initialize_empty_tenant_coverage(self, session: Session, tenant_id: int, writer_contract_version: str) -> None:
        identity = self._initialization_context(session, tenant_id, writer_contract_version)
        try:
            self.initializer.initialize_empty_tenant_coverage(session, tenant_id, writer_contract_version)
            identity.assert_current(session)
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as exc:
            raise ReferenceCoverageNotReadyError(reason="coverage_initialization_failed") from exc

    async def ainitialize_empty_tenant_coverage(
        self, session: AsyncSession, tenant_id: int, writer_contract_version: str
    ) -> None:
        identity = self._initialization_context(session, tenant_id, writer_contract_version)
        try:
            await self.initializer.ainitialize_empty_tenant_coverage(session, tenant_id, writer_contract_version)
            identity.assert_current(session)
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as exc:
            raise ReferenceCoverageNotReadyError(reason="coverage_initialization_failed") from exc
