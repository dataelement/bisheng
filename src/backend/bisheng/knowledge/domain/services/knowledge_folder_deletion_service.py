"""Owns the observable lifetime of synchronous folder deletion."""

import asyncio
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

from loguru import logger
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from bisheng.common.errcode.knowledge_space import SpaceFileChangeConflictError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.folder_deletion import (
    STALE_AFTER,
    DeletionStatus,
    FolderStatus,
    as_utc,
    marker_for,
    project_folder,
)
from bisheng.knowledge.domain.repositories.knowledge_folder_deletion_repository import (
    FolderLockBusy,
    KnowledgeFolderDeletionRepository,
)
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL
from bisheng.permission.application.identity import resolve_permission_actor


class FolderCommitUncertain(Exception):
    """The transaction body completed, but its commit was not acknowledged."""

    def __init__(self, message, operation_id=None):
        super().__init__(message)
        self.operation_id = operation_id


@asynccontextmanager
async def delete_transaction(session, tracked, operation_id=None):
    finalizing = False
    try:
        async with session.begin():
            yield
            finalizing = True
    except Exception as exc:
        if tracked and finalizing:
            raise FolderCommitUncertain("Folder transaction commit could not be confirmed", operation_id) from exc
        raise


class KnowledgeFolderDeletionService:
    def __init__(self, space_id, session_factory=get_async_db_session):
        self.tenant_id = get_current_tenant_id()
        self.space_id = space_id
        self.sessions = session_factory

    def repository(self, session):
        if self.tenant_id is None:
            raise RuntimeError("folder deletion requires tenant context")
        return KnowledgeFolderDeletionRepository(session, self.tenant_id, self.space_id)

    async def _update(self, folder_id, token, **options):
        # NOWAIT is a statement-level cap below both the one-second heartbeat
        # and five-second reconcile limits, without modifying a pooled connection.
        try:
            async with self.sessions() as session, session.begin():
                if options.get("reconcile") or options.get("reason") is None:
                    # Bound connection acquisition separately. No folder lock
                    # statement has been submitted while waiting for the pool.
                    budget = 5 if options.get("reconcile") else 1
                    try:
                        await asyncio.wait_for(session.connection(), timeout=budget)
                    except TimeoutError as exc:
                        raise PoolTimeout("Folder status connection unavailable") from exc
                changed = await self.repository(session).update_running(folder_id, token, **options)
            if changed and options.get("reason"):
                logger.info(
                    "Folder deletion ended tenant={} space={} folder={} operation={} reason={}",
                    self.tenant_id,
                    self.space_id,
                    folder_id,
                    token,
                    options["reason"],
                )
            return changed
        except FolderLockBusy:
            logger.debug(
                "Folder deletion root busy tenant={} space={} folder={} operation={}",
                self.tenant_id,
                self.space_id,
                folder_id,
                token,
            )
            return False

    async def _heartbeat(self, folder_id, token, stop):
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=10)
                return
            except TimeoutError:
                try:
                    await self._update(folder_id, token)
                except SQLAlchemyError:
                    # Renewal is best effort. The holder still checks its fence
                    # inside the cutover transaction and never relies on freshness.
                    logger.warning("Folder deletion heartbeat unavailable folder={} operation={}", folder_id, token)

    @asynccontextmanager
    async def track(self, folder_id, user_id):
        token = str(uuid4())
        async with self.sessions() as session, delete_transaction(session, True, token):
            repo = self.repository(session)
            # Read the committed marker first: a repeated DELETE need not wait
            # behind a long-running manifest transaction to report its conflict.
            current = (await repo.folders([folder_id])).get(folder_id)
            if current and current.status == FolderStatus.DELETING:
                raise SpaceFileChangeConflictError(operation_id=(marker_for(current) or {}).get("operation_id"))
            await repo.claim(folder_id, token, user_id)
        logger.info(
            "Folder deletion registered tenant={} space={} folder={} operation={}",
            self.tenant_id,
            self.space_id,
            folder_id,
            token,
        )
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(folder_id, token, stop))
        try:
            yield token
        except FolderCommitUncertain as exc:
            exc.operation_id = token
            raise
        except (ConnectionError, TimeoutError) as exc:
            raise FolderCommitUncertain("Folder deletion result is unknown", token) from exc
        except Exception as exc:
            if isinstance(exc, DBAPIError) and exc.connection_invalidated:
                raise FolderCommitUncertain("Folder connection lost", token) from exc
            try:
                await self._update(folder_id, token, reason="delete_failed")
            except SQLAlchemyError:
                # Preserve the original business failure. A later authorized
                # reconcile can safely recover the marker after DB availability.
                logger.warning("Could not record folder deletion failure folder={} operation={}", folder_id, token)
            raise
        finally:
            stop.set()
            # Cancellation also interrupts a pending pool checkout. The session
            # manager rolls back and closes in-flight work; the main transaction
            # has already released its locks at this point.
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    @staticmethod
    def _approval(item, row):
        if not row or row.resource_id != item.folder_id:
            item.state = "unknown"
        elif row.cutover_state == "succeeded":
            item.state = "succeeded"
        elif row.execution_state == "not_started":
            item.state = "approval_pending"
        elif row.execution_state in {"queued", "applying", "compensating"}:
            fresh = row.update_time and as_utc(row.db_local_now) - as_utc(row.update_time) < STALE_AFTER
            item.state = "running" if fresh else "unknown"
        elif row.execution_state in {"failed", "closed"}:
            item.state = "failed"
            item.failure_reason = "approval_ended"
        else:
            item.state = "unknown"
        item.retry_after_ms = 3000 if item.state in {"running", "unknown", "approval_pending"} else None
        return item

    @staticmethod
    def _ordinary_approval_id(token):
        suffix = token.removeprefix("approval-") if isinstance(token, str) and token.startswith("approval-") else ""
        if suffix.isascii() and suffix.isdigit() and 0 < len(suffix) <= 18:
            return int(suffix) if str(int(suffix)) == suffix else None
        return None

    @classmethod
    def _known_ledger(cls, fid, token, by_key, by_id):
        row = by_key.get(f"direct-delete:{token}") or by_key.get(f"folder-delete-approval:{token}")
        if not row:
            row = by_id.get(cls._ordinary_approval_id(token))
            if row and (not row.approval_instance_id or row.business_key.startswith("folder-delete-approval:")):
                return None
        return row if row and row.resource_id == fid else None

    @classmethod
    def _visible_item(cls, root, now, token, row, by_id, active, *, user_id, space_visible, manager):
        item = project_folder(root, now)
        marker = marker_for(root) or {}
        initiator = marker.get("initiator_user_id")
        if item.state == "approval_pending":
            linked = by_id.get(marker.get("approval_request_id"))
            if linked and linked.business_key != f"folder-delete-approval:{item.operation_id}":
                linked = None
            cls._approval(item, linked)
        elif item.state == "idle":
            if active:
                item.operation_id = f"approval-{active.id}"
                initiator = active.applicant_user_id
                cls._approval(item, active)
            elif row and row.approval_instance_id:
                item.operation_id = token
                initiator = row.applicant_user_id
                cls._approval(item, row)
            elif token:
                if not manager:
                    return DeletionStatus(folder_id=root.id, state="unavailable")
                item.state, item.operation_id = "untracked", token
        if item.state in {"failed", "succeeded"} and not (manager or (space_visible and initiator == user_id)):
            return DeletionStatus(folder_id=root.id, state="unavailable" if token else "idle")
        if item.state == "unknown" and root.status == FolderStatus.DELETING:
            item.can_reconcile = bool(
                marker.get("phase") == "running"
                and (manager or (space_visible and marker["initiator_user_id"] == user_id))
            )
        return item

    @staticmethod
    def _vanished_item(fid, token, row, *, user_id, space_visible, manager):
        if not (manager or (row and space_visible and row.applicant_user_id == user_id)):
            return DeletionStatus(folder_id=fid, state="unavailable")
        item = DeletionStatus(folder_id=fid, operation_id=token, state="untracked")
        if row and row.cutover_state == "succeeded" and (row.approval_instance_id or row.execution_token == token):
            item.state = "succeeded"
        return item

    async def _visible_resources(self, owner, rows, space):
        # Match the space listing's unrestricted super-admin view. A narrowed
        # token must still pass the ordinary per-resource visibility checks.
        if getattr(owner.login_user, "is_global_super", False):
            actor = await resolve_permission_actor(owner.login_user)
            if actor.super_admin and actor.data_scope == DATA_SCOPE_ALL:
                return rows
        return await owner._filter_visible_child_items(rows, space_id=self.space_id, context={"verified_space": space})

    async def query(self, owner, folder_ids, known):
        space, _ = await owner._load_space_listing_scope(self.space_id, None)
        space_rights = (
            await owner._batch_actions("knowledge_space", [self.space_id], ("visible", "manage_permission"))
        ).get(str(self.space_id), ())
        audience = {
            "user_id": int(owner.login_user.user_id),
            "space_visible": "visible" in space_rights,
            "manager": "manage_permission" in space_rights,
        }
        # PermissionService may check out its own DB connection. Release the
        # business read before calling it, including for inherited ancestors.
        async with self.sessions() as session:
            roots = await self.repository(session).requested_resources(folder_ids)
        visible = {row.id for row in await self._visible_resources(owner, list(roots.values()), space)}
        visible_folders = {fid for fid in visible if roots[fid].file_type == 0}
        markers = [marker_for(roots[fid]) or {} for fid in visible_folders]
        approvals = [m["approval_request_id"] for m in markers if m.get("approval_request_id")]
        approvals.extend(req_id for token in known.values() if (req_id := self._ordinary_approval_id(token)))
        async with self.sessions() as session:
            repo = self.repository(session)
            now = await repo.now()
            evidence = await repo.ledgers(request_ids=approvals, tokens=list(known.values()))
            active = {row.resource_id: row for row in await repo.ledgers(active_folders=visible_folders)}
        inherited = await self._range_states([roots[fid] for fid in visible], visible_folders, owner, space, now=now)
        by_id = {row.id: row for row in evidence}
        by_key = {row.business_key: row for row in evidence}
        items = []
        for fid in dict.fromkeys(folder_ids):
            token = known.get(fid)
            row = self._known_ledger(fid, token, by_key, by_id)
            scope = inherited.get(fid)
            if fid in visible and scope and (fid not in visible_folders or roots[fid].status != FolderStatus.DELETING):
                # Inherited anchors carry no execution identity. Only the
                # actual root can reconcile or look up a historical ledger.
                item = DeletionStatus(folder_id=fid, state=scope["state"], retry_after_ms=scope["retry_after_ms"])
            elif fid in visible_folders:
                item = self._visible_item(roots[fid], now, token, row, by_id, active.get(fid), **audience)
            elif fid in visible:
                item = DeletionStatus(folder_id=fid, state="idle")
            elif fid in roots:
                item = DeletionStatus(folder_id=fid, state="unavailable")
            else:
                item = self._vanished_item(fid, token, row, **audience)
            items.append(item)
        return items

    async def reconcile(self, owner, folder_id, token):
        (item,) = await self.query(owner, [folder_id], {folder_id: token})
        if item.operation_id != token or not item.can_reconcile:
            return item
        try:
            await self._update(folder_id, token, reason="interrupted", reconcile=True)
            (item,) = await self.query(owner, [folder_id], {folder_id: token})
        except PoolTimeout:
            # Authorization succeeded. Pool exhaustion proves nothing about the
            # outcome; keep the last confirmed unknown projection for retry.
            logger.warning("Folder reconciliation unavailable folder={} operation={}", folder_id, token)
        return item

    @staticmethod
    def _folder_path(row):
        ids = [int(part) for part in str(row.file_level_path or "").split("/") if part]
        if row.file_type == 0:
            ids.append(row.id)
        return ids

    async def _range_states(self, rows, visible_folders, owner, space, *, now=None):
        paths = {row.id: self._folder_path(row) for row in rows}
        folders = {row.id: row for row in rows if row.file_type == 0}
        missing = {fid for path in paths.values() for fid in path} - folders.keys()
        if not missing and not any(folder.status == FolderStatus.DELETING for folder in folders.values()):
            return {}
        async with self.sessions() as session:
            repo = self.repository(session)
            if missing:
                folders.update(await repo.folders(sorted(missing)))
            deleting = {fid: row for fid, row in folders.items() if row.status == FolderStatus.DELETING}
            if not deleting:
                return {}
            if now is None:
                now = await repo.now()
        active = {fid: project_folder(row, now) for fid, row in deleting.items()}
        unverified = [row for fid, row in folders.items() if fid not in visible_folders]
        visible_folders = set(visible_folders)
        if unverified and owner is not None:
            for start in range(0, len(unverified), 500):
                granted = await self._visible_resources(owner, unverified[start : start + 500], space)
                visible_folders.update(row.id for row in granted)
        result = {}
        for resource_id, path in paths.items():
            for index, fid in enumerate(path):
                if fid in active:
                    item = active[fid]
                    # Redact the hidden root id/token. The first visible
                    # descendant (or directly shared file) is safe to poll.
                    anchor = next((part for part in path[index:] if part in visible_folders), resource_id)
                    result[resource_id] = {
                        "root_folder_id": anchor,
                        "operation_id": item.operation_id if anchor == fid else None,
                        "state": item.state,
                        "retry_after_ms": item.retry_after_ms,
                    }
                    break
        return result

    async def project_page(self, rows, items, parent, *, owner=None, space=None):
        resources = list(rows)
        if parent:
            resources.append(parent)
        states = await self._range_states(resources, {row.id for row in resources if row.file_type == 0}, owner, space)
        for row, item in zip(rows, items, strict=True):
            item["deletion_status"] = states.get(row.id)
        return states.get(parent.id) if parent else None
