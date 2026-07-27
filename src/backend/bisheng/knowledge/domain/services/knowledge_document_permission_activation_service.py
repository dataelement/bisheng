"""OpenFGA-first activation saga for F059 entries."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence

from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    KnowledgeFileRepository,
)
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation

logger = logging.getLogger(__name__)

TupleWriter = Callable[[list[TupleOperation]], Awaitable[None]]


class KnowledgeDocumentPermissionActivationError(RuntimeError):
    """Raised when an entry permission saga cannot safely advance."""


async def _default_tuple_writer(operations: list[TupleOperation]) -> None:
    from bisheng.permission.domain.services.permission_service import (
        PermissionService,
    )

    await PermissionService.batch_write_tuples(
        operations,
        crash_safe=True,
        raise_on_failure=True,
        stop_on_failure=True,
    )


class KnowledgeDocumentPermissionActivationService:
    def __init__(
        self,
        *,
        file_repository: KnowledgeFileRepository,
        tuple_writer: TupleWriter = _default_tuple_writer,
    ):
        self.file_repository = file_repository
        self.tuple_writer = tuple_writer

    @staticmethod
    def _parent_operation(
        entry: KnowledgeFile,
        *,
        action: str,
    ) -> TupleOperation:
        folder_ids = [
            int(part)
            for part in str(entry.file_level_path or "").split("/")
            if part.isdigit() and int(part) > 0
        ]
        if folder_ids:
            parent_type = "folder"
            parent_id = folder_ids[-1]
        else:
            parent_type = "knowledge_space"
            parent_id = int(entry.knowledge_id)
        return TupleOperation(
            action=action,
            user=f"{parent_type}:{parent_id}",
            relation="parent",
            object=f"knowledge_file:{int(entry.id)}",
        )

    def build_parent_operation(
        self,
        entry: KnowledgeFile,
        *,
        action: str,
    ) -> TupleOperation:
        return self._parent_operation(entry, action=action)

    @staticmethod
    def _normalize_operations(
        operations: Sequence[TupleOperation],
        *,
        action: str,
    ) -> list[TupleOperation]:
        return [
            TupleOperation(
                action=action,
                user=operation.user,
                relation=operation.relation,
                object=operation.object,
            )
            for operation in operations
        ]

    async def prewrite_and_activate(
        self,
        *,
        entry_id: int,
        explicit_operations: Sequence[TupleOperation] = (),
    ) -> bool:
        entry = await self.file_repository.find_by_id(entry_id)
        if entry is None:
            raise KnowledgeDocumentPermissionActivationError(
                "entry does not exist"
            )
        if entry.entry_status == KnowledgeFileEntryStatus.ACTIVE.value:
            return False
        if entry.entry_status != KnowledgeFileEntryStatus.PREPARING.value:
            raise KnowledgeDocumentPermissionActivationError(
                "only a preparing entry can be activated"
            )

        operations = [
            self._parent_operation(entry, action="write"),
            *self._normalize_operations(
                explicit_operations,
                action="write",
            ),
        ]
        try:
            await self.tuple_writer(operations)
        except Exception as exc:
            logger.exception(
                "F059 permission prewrite failed for entry_id=%s",
                entry_id,
            )
            raise KnowledgeDocumentPermissionActivationError(
                "permission prewrite failed; entry remains preparing"
            ) from exc

        activated = await self.file_repository.activate_prepared_entry(
            entry_id
        )
        if activated:
            return True

        refreshed = await self.file_repository.find_by_id(entry_id)
        if (
            refreshed is not None
            and refreshed.entry_status
            == KnowledgeFileEntryStatus.ACTIVE.value
        ):
            return False
        raise KnowledgeDocumentPermissionActivationError(
            "permission prewrite succeeded but DB activation did not apply"
        )

    async def prewrite_entry_permissions(
        self,
        *,
        entry: KnowledgeFile,
        explicit_operations: Sequence[TupleOperation] = (),
        additional_operations: Sequence[TupleOperation] = (),
    ) -> None:
        if entry.entry_status != KnowledgeFileEntryStatus.PREPARING.value:
            raise KnowledgeDocumentPermissionActivationError(
                "permission prewrite requires a preparing entry"
            )
        operations = [
            self._parent_operation(entry, action="write"),
            *self._normalize_operations(
                explicit_operations,
                action="write",
            ),
            *list(additional_operations),
        ]
        try:
            await self.tuple_writer(operations)
        except Exception as exc:
            logger.exception(
                "F059 permission prewrite failed for entry_id=%s",
                entry.id,
            )
            raise KnowledgeDocumentPermissionActivationError(
                "permission prewrite failed; entry remains preparing"
            ) from exc

    async def revoke_deleting_entry(
        self,
        *,
        entry_id: int,
        explicit_operations: Sequence[TupleOperation] = (),
    ) -> bool:
        entry = await self.file_repository.find_by_id(entry_id)
        if entry is None:
            return False
        if entry.entry_status != KnowledgeFileEntryStatus.DELETING.value:
            raise KnowledgeDocumentPermissionActivationError(
                "only a deleting entry can revoke permissions"
            )

        operations = [
            self._parent_operation(entry, action="delete"),
            *self._normalize_operations(
                explicit_operations,
                action="delete",
            ),
        ]
        try:
            await self.tuple_writer(operations)
        except Exception as exc:
            logger.exception(
                "F059 permission revoke failed for entry_id=%s",
                entry_id,
            )
            raise KnowledgeDocumentPermissionActivationError(
                "permission revoke failed; deleting entry remains hidden"
            ) from exc
        return True
