"""Small, tenant-scoped transactions on the existing folder and F046 rows."""

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from bisheng.common.errcode.knowledge_space import SpaceFileChangeConflictError, SpaceFolderNotFoundError
from bisheng.knowledge.domain.models.folder_deletion import (
    RESERVED_KEY,
    FolderStatus,
    as_utc,
    ensure_owner,
    make_marker,
    marker_for,
    project_folder,
    public_metadata,
)
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep as Step,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeFootprint as Footprint,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeRequest as Request,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_footprint_repository import (
    RESOURCE_LOCK_BLOCKING_EXECUTION_STATES,
    FootprintEntry,
    KnowledgeSpaceFileChangeFootprintRepository,
)


class FolderLockBusy(Exception):
    """A statement-scoped NOWAIT probe found the root owned by another writer."""


class KnowledgeFolderDeletionRepository:
    def __init__(self, session, tenant_id, space_id):
        self.session = session
        self.tenant_id = int(tenant_id)
        self.space_id = int(space_id)

    async def now(self):
        dialect = self.session.get_bind().dialect.name
        clock = func.current_timestamp()
        if dialect == "mysql":
            clock = func.utc_timestamp()
        elif dialect == "dm":
            clock = func.sys_extract_utc(func.current_timestamp())
        return as_utc((await self.session.exec(select(clock))).one())

    def _folders(self):
        return select(KnowledgeFile).where(
            KnowledgeFile.tenant_id == self.tenant_id,
            KnowledgeFile.knowledge_id == self.space_id,
            KnowledgeFile.file_type == 0,
        )

    async def folders(self, ids):
        ids = list(dict.fromkeys(ids))
        result = {}
        for offset in range(0, len(ids), 500):
            rows = await self.session.exec(self._folders().where(KnowledgeFile.id.in_(ids[offset : offset + 500])))
            result.update((row.id, row) for row in rows)
        return result

    async def requested_resources(self, ids):
        # A directly granted file can be the only public anchor below a hidden
        # deleting folder. Its own parsing status is never a deletion marker.
        rows = await self.session.exec(
            select(KnowledgeFile).where(
                KnowledgeFile.tenant_id == self.tenant_id,
                KnowledgeFile.knowledge_id == self.space_id,
                KnowledgeFile.id.in_(list(ids)),
            )
        )
        return {row.id: row for row in rows}

    async def locked(self, folder_id, *, nowait=False):
        stmt = self._folders().where(KnowledgeFile.id == folder_id).execution_options(populate_existing=True)
        if nowait and self.session.get_bind().dialect.name in {"dm", "mysql"}:
            # The DM driver need not implement SQLAlchemy's nowait flag. The SQL
            # clause is supported by both production databases and changes no pool settings.
            stmt = stmt.suffix_with("FOR UPDATE NOWAIT")
        else:
            stmt = stmt.with_for_update(nowait=nowait)
        try:
            return (await self.session.exec(stmt)).first()
        except DBAPIError as exc:
            args = exc.orig.args
            if nowait and (3572 in args or 1205 in args or "-6407" in str(exc.orig)):
                raise FolderLockBusy() from exc
            raise

    @staticmethod
    def write(folder, status, marker):
        folder.status = status.value
        folder.user_metadata = {**(folder.user_metadata or {}), RESERVED_KEY: marker}

    async def claim(self, folder_id, token, user_id):
        folder = await self.locked(folder_id)
        if not folder:
            raise SpaceFolderNotFoundError()
        marker = marker_for(folder)
        conflict = SpaceFileChangeConflictError(operation_id=(marker or {}).get("operation_id"))
        if folder.status != FolderStatus.NORMAL:
            raise conflict
        footprint = FootprintEntry(
            space_id=self.space_id,
            resource_type="folder",
            resource_id=folder_id,
            path_root=f"{folder.file_level_path or ''}/{folder_id}",
            lock_scope="subtree",
        )
        if await KnowledgeSpaceFileChangeFootprintRepository(self.session).find_blocking_request_ids(
            tenant_id=self.tenant_id, footprints=[footprint]
        ):
            raise conflict
        await self.require_previous_approval_ended(folder)
        self.write(folder, FolderStatus.DELETING, make_marker(token, user_id, await self.now()))

    @staticmethod
    def clear_marker(folder):
        folder.user_metadata = public_metadata(folder.user_metadata)

    async def require_previous_approval_ended(self, folder):
        marker = marker_for(folder)
        if not marker or marker.get("phase") != "approval_pending":
            return
        rows = await self.ledgers(request_ids=[marker.get("approval_request_id")])
        if (
            not rows
            or rows[0].resource_id != folder.id
            or rows[0].business_key != f"folder-delete-approval:{marker['operation_id']}"
            or rows[0].execution_state not in {"closed", "applied"}
        ):
            raise SpaceFileChangeConflictError(operation_id=marker["operation_id"])

    async def update_running(self, folder_id, token, *, reason=None, reconcile=False):
        folder = await self.locked(folder_id, nowait=(reason is None or reconcile))
        if not folder:
            return False
        marker = marker_for(folder)
        if not (
            marker
            and marker.get("phase") == "running"
            and marker["operation_id"] == token
            and folder.status == FolderStatus.DELETING
        ):
            return False
        now = await self.now()
        if reconcile and project_folder(folder, now).state != "unknown":
            return False
        if reason:
            self.write(folder, FolderStatus.NORMAL, {**marker, "phase": "failed", "failure_reason": reason})
        else:
            self.write(folder, FolderStatus.DELETING, {**marker, "heartbeat_at": now.isoformat()})
        return True

    async def attach_approval(self, folder, token, request_id):
        ensure_owner(folder, token)
        self.write(
            folder,
            FolderStatus.NORMAL,
            {**marker_for(folder), "phase": "approval_pending", "approval_request_id": request_id},
        )

    async def ledgers(self, *, request_ids=(), tokens=(), active_folders=()):
        """Only read scalar evidence; the execution checkpoint can contain an entire subtree."""
        conditions = []
        if request_ids:
            conditions.append(Request.id.in_(list(request_ids)))
        if tokens:
            keys = [f"{prefix}:{token}" for token in tokens for prefix in ("direct-delete", "folder-delete-approval")]
            conditions.append(Request.business_key.in_(keys))
        if active_folders:
            active = select(Footprint.request_id).where(
                Footprint.tenant_id == self.tenant_id,
                Footprint.space_id == self.space_id,
                Footprint.resource_type == "folder",
                Footprint.resource_id.in_(list(active_folders)),
            )
            conditions.append(
                and_(
                    Request.id.in_(active),
                    Request.resource_id.in_(list(active_folders)),
                    Request.approval_instance_id.is_not(None),
                    Request.execution_state.in_(RESOURCE_LOCK_BLOCKING_EXECUTION_STATES),
                )
            )
        if not conditions:
            return []
        stmt = (
            select(
                Request.id,
                Request.resource_id,
                Request.applicant_user_id,
                Request.business_key,
                Request.execution_state,
                Request.execution_token,
                Request.approval_instance_id,
                Request.update_time,
                func.current_timestamp().label("db_local_now"),
                Step.state.label("cutover_state"),
            )
            .outerjoin(
                Step,
                and_(
                    Step.tenant_id == Request.tenant_id,
                    Step.request_id == Request.id,
                    Step.step_code == "delete.db_cutover",
                    Step.attempt_token == Request.execution_token,
                ),
            )
            .where(
                Request.tenant_id == self.tenant_id,
                Request.space_id == self.space_id,
                Request.resource_type == "folder",
                Request.action == "delete",
                or_(*conditions),
            )
        )
        return list((await self.session.exec(stmt)).all())
