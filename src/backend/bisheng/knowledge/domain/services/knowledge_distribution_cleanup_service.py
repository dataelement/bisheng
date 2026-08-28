"""Batch cleanup of distribution entries whose container is being deleted.

Deleting a folder or a knowledge space used to be refused outright when it held
published or shared files, which left administrators unpicking dozens of files
by hand. This service sweeps them instead: every entry follows exactly the rule
it would follow if the user had deleted it on its own, so there is one rule to
learn rather than one per entry point.

Two properties matter more than speed here:

* **One bad entry must not strand the container.** A knowledge space waits for
  its entries to finish cleanup before it disappears, so an entry that can
  never be processed would leave the space retiring forever. Every failure is
  recorded and the sweep moves on.
* **Shortcuts must leave the chain connected.** The strict detach refuses a
  chain it cannot prove; here that refusal is downgraded to a forced detach
  rather than allowed to block the sweep.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
)
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
    KnowledgeDocumentDistributionError,
    KnowledgeDocumentDistributionService,
)

logger = logging.getLogger(__name__)


class EntryCleanupAction(str, Enum):
    ROLLBACK = "rollback"
    FINAL_DELETE = "final_delete"
    DETACHED = "detached"
    FORCE_DETACHED = "force_detached"
    SHARE_REVOKED = "share_revoked"
    INVALID_REMOVED = "invalid_removed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class EntryCleanupOutcome:
    entry_id: int
    entry_type: str
    action: EntryCleanupAction
    degraded: bool = False
    error: str | None = None


class KnowledgeDistributionCleanupService:
    def __init__(self, *, distribution_service: KnowledgeDocumentDistributionService):
        self.distribution_service = distribution_service

    async def cleanup_entries(
        self,
        entries: Sequence[KnowledgeFile],
    ) -> list[EntryCleanupOutcome]:
        """Process every entry, reporting per-entry results instead of raising."""
        outcomes: list[EntryCleanupOutcome] = []
        for entry in entries:
            outcomes.append(await self.cleanup_entry(entry))
        return outcomes

    async def cleanup_entry(self, entry: KnowledgeFile) -> EntryCleanupOutcome:
        tenant_id = int(entry.tenant_id or 0)
        entry_id = int(entry.id)
        entry_type = str(entry.entry_type or "")
        document_id = int(entry.reference_document_id or 0)

        if not document_id:
            return self._outcome(entry_id, entry_type, EntryCleanupAction.SKIPPED)
        if entry.entry_status == KnowledgeFileEntryStatus.DELETING.value:
            # Already on its way out; the projection worker owns it from here.
            return self._outcome(entry_id, entry_type, EntryCleanupAction.SKIPPED)

        try:
            if entry.entry_status == KnowledgeFileEntryStatus.INVALID.value:
                await self.distribution_service.remove_invalid_entry(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    entry_id=entry_id,
                )
                return self._outcome(entry_id, entry_type, EntryCleanupAction.INVALID_REMOVED)

            if entry_type == KnowledgeFileEntryType.PUBLISH.value:
                return await self._cleanup_publish(tenant_id, document_id, entry_id, entry_type)

            if entry_type == KnowledgeFileEntryType.SHARE.value:
                await self.distribution_service.remove_share_entry(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    share_entry_id=entry_id,
                    # The recipient space is the one going away, so it revokes
                    # its own share rather than acting through the manager.
                    actor_entry_id=entry_id,
                )
                return self._outcome(entry_id, entry_type, EntryCleanupAction.SHARE_REVOKED)

            if entry_type == KnowledgeFileEntryType.MANAGER.value:
                result = await self.distribution_service.delete_manager(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    manager_file_id=entry_id,
                )
                action = (
                    EntryCleanupAction.ROLLBACK
                    if result.action == "rollback"
                    else EntryCleanupAction.FINAL_DELETE
                )
                return self._outcome(entry_id, entry_type, action)

            # Projection tombstones are internal bookkeeping the projection
            # worker clears on its own.
            return self._outcome(entry_id, entry_type, EntryCleanupAction.SKIPPED)
        except KnowledgeDocumentDistributionError as exc:
            logger.warning(
                "F098 container cleanup could not process entry_id=%s type=%s: %s",
                entry_id,
                entry_type,
                exc,
            )
            return self._outcome(
                entry_id,
                entry_type,
                EntryCleanupAction.FAILED,
                error=str(exc),
            )
        except Exception as exc:
            logger.exception(
                "F098 container cleanup failed unexpectedly entry_id=%s type=%s",
                entry_id,
                entry_type,
            )
            return self._outcome(
                entry_id,
                entry_type,
                EntryCleanupAction.FAILED,
                error=str(exc),
            )

    async def _cleanup_publish(
        self,
        tenant_id: int,
        document_id: int,
        entry_id: int,
        entry_type: str,
    ) -> EntryCleanupOutcome:
        try:
            await self.distribution_service.remove_publish_entry(
                tenant_id=tenant_id,
                document_id=document_id,
                publish_entry_id=entry_id,
            )
            return self._outcome(entry_id, entry_type, EntryCleanupAction.DETACHED)
        except KnowledgeDocumentDistributionError as exc:
            # The strict path refuses chains it cannot prove. Refusing here
            # would leave the container waiting on this entry forever, so drop
            # to the forced detach, which relinks whatever points at it.
            logger.warning(
                "F098 strict detach refused entry_id=%s, degrading to forced detach: %s",
                entry_id,
                exc,
            )
            await self.distribution_service.force_detach_publish_entry(
                tenant_id=tenant_id,
                document_id=document_id,
                publish_entry_id=entry_id,
            )
            return self._outcome(
                entry_id,
                entry_type,
                EntryCleanupAction.FORCE_DETACHED,
                degraded=True,
            )

    @staticmethod
    def _outcome(
        entry_id: int,
        entry_type: str,
        action: EntryCleanupAction,
        *,
        degraded: bool = False,
        error: str | None = None,
    ) -> EntryCleanupOutcome:
        return EntryCleanupOutcome(
            entry_id=entry_id,
            entry_type=entry_type,
            action=action,
            degraded=degraded,
            error=error,
        )
