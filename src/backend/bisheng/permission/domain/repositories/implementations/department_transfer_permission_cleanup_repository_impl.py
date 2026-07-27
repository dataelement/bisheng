from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
    DepartmentTransferCleanupEventStatus,
    DepartmentTransferCleanupItemStatus,
    DepartmentTransferPermissionCleanupEvent,
    DepartmentTransferPermissionCleanupItem,
)
from bisheng.permission.domain.repositories.interfaces.department_transfer_permission_cleanup_repository import (
    DepartmentTransferPermissionCleanupRepository,
)


class DepartmentTransferPermissionCleanupRepositoryImpl(
    BaseRepositoryImpl[DepartmentTransferPermissionCleanupEvent, int],
    DepartmentTransferPermissionCleanupRepository,
):
    def __init__(self, session: AsyncSession):
        super().__init__(session, DepartmentTransferPermissionCleanupEvent)

    async def find_active_matching_event(
        self,
        *,
        tenant_id: int,
        user_id: int,
        old_department_id: int,
        new_department_id: int,
        trigger_source: str,
    ) -> DepartmentTransferPermissionCleanupEvent | None:
        result = await self.session.execute(
            select(DepartmentTransferPermissionCleanupEvent)
            .where(
                DepartmentTransferPermissionCleanupEvent.tenant_id == tenant_id,
                DepartmentTransferPermissionCleanupEvent.user_id == user_id,
                DepartmentTransferPermissionCleanupEvent.old_department_id == old_department_id,
                DepartmentTransferPermissionCleanupEvent.new_department_id == new_department_id,
                DepartmentTransferPermissionCleanupEvent.trigger_source == trigger_source,
                ~col(DepartmentTransferPermissionCleanupEvent.status).in_(
                    DepartmentTransferCleanupEventStatus.TERMINAL,
                ),
            )
            .order_by(DepartmentTransferPermissionCleanupEvent.id.desc())
            .with_for_update()
        )
        return result.scalars().first()

    async def create_or_get_event(
        self,
        *,
        tenant_id: int,
        event_key: str,
        user_id: int,
        old_department_id: int,
        new_department_id: int,
        trigger_source: str,
        requested_at: datetime,
    ) -> DepartmentTransferPermissionCleanupEvent:
        statement = (
            select(DepartmentTransferPermissionCleanupEvent)
            .where(DepartmentTransferPermissionCleanupEvent.event_key == event_key)
            .with_for_update()
        )
        result = await self.session.execute(statement)
        event = result.scalars().first()
        if event is None:
            event = DepartmentTransferPermissionCleanupEvent(
                tenant_id=tenant_id,
                event_key=event_key,
                user_id=user_id,
                old_department_id=old_department_id,
                new_department_id=new_department_id,
                trigger_source=trigger_source,
                requested_at=requested_at,
            )
            self.session.add(event)
            await self.session.flush()
        return event

    async def activate_event(
        self,
        event_id: int,
        *,
        changed_at: datetime,
        deadline_at: datetime,
    ) -> DepartmentTransferPermissionCleanupEvent | None:
        event = await self._event_for_update(event_id)
        if event is None or event.status in DepartmentTransferCleanupEventStatus.TERMINAL:
            return event
        event.status = DepartmentTransferCleanupEventStatus.PENDING
        event.changed_at = event.changed_at or changed_at
        event.deadline_at = event.deadline_at or deadline_at
        event.next_retry_at = changed_at
        event.last_error = None
        self.session.add(event)
        await self.session.flush()
        return event

    async def cancel_event(
        self,
        event_id: int,
        *,
        reason: str,
    ) -> DepartmentTransferPermissionCleanupEvent | None:
        event = await self._event_for_update(event_id)
        if event is None or event.status in DepartmentTransferCleanupEventStatus.TERMINAL:
            return event
        event.status = DepartmentTransferCleanupEventStatus.CANCELLED
        event.last_error = self._sanitize_error(reason)
        event.next_retry_at = None
        self.session.add(event)
        await self.session.flush()
        return event

    async def upsert_item(
        self,
        *,
        tenant_id: int,
        event_id: int,
        item_key: str,
        item_type: str,
        user_id: int,
        resource_type: str,
        resource_id: str,
        root_space_id: int | None,
        relation: str | None,
        source_ref: str | None,
        snapshot: dict,
        status: str = DepartmentTransferCleanupItemStatus.PENDING,
        last_error: str | None = None,
    ) -> DepartmentTransferPermissionCleanupItem:
        item = await self._item_for_update(event_id, item_key)
        if item is None:
            item = DepartmentTransferPermissionCleanupItem(
                tenant_id=tenant_id,
                event_id=event_id,
                item_key=item_key,
                item_type=item_type,
                user_id=user_id,
                resource_type=resource_type,
                resource_id=str(resource_id),
                root_space_id=root_space_id,
                relation=relation,
                source_ref=source_ref,
                snapshot=snapshot,
                status=status,
                last_error=self._sanitize_error(last_error),
            )
            self.session.add(item)
            await self.session.flush()
            return item
        if item.status in DepartmentTransferCleanupItemStatus.TERMINAL:
            return item
        item.root_space_id = root_space_id
        item.source_ref = source_ref
        item.snapshot = snapshot
        item.last_error = self._sanitize_error(last_error)
        self.session.add(item)
        await self.session.flush()
        return item

    async def protect_item(
        self,
        *,
        event_id: int,
        item_key: str,
        source: str,
        protected_at: datetime,
        tenant_id: int,
        user_id: int,
        item_type: str,
        resource_type: str,
        resource_id: str,
        relation: str | None,
        snapshot: dict,
    ) -> DepartmentTransferPermissionCleanupItem:
        item = await self._item_for_update(event_id, item_key)
        if item is None:
            item = DepartmentTransferPermissionCleanupItem(
                tenant_id=tenant_id,
                event_id=event_id,
                item_key=item_key,
                item_type=item_type,
                user_id=user_id,
                resource_type=resource_type,
                resource_id=str(resource_id),
                relation=relation,
                snapshot=snapshot,
            )
        if item.status in DepartmentTransferCleanupItemStatus.PROCESSABLE:
            item.status = DepartmentTransferCleanupItemStatus.PROTECTED
            item.protected_at = protected_at
            item.protected_source = source
            item.processed_at = protected_at
            item.last_error = None
        self.session.add(item)
        await self.session.flush()
        return item

    async def claim_event(self, event_id: int, *, now: datetime) -> bool:
        event = await self._event_for_update(event_id)
        claimable_statuses = DepartmentTransferCleanupEventStatus.RETRYABLE | {
            DepartmentTransferCleanupEventStatus.PROCESSING,
        }
        if event is None or event.status not in claimable_statuses:
            return False
        if event.next_retry_at is not None and event.next_retry_at > now:
            return False
        event.status = DepartmentTransferCleanupEventStatus.PROCESSING
        event.retry_count += 1
        event.next_retry_at = now.replace(microsecond=0) + timedelta(seconds=30)
        self.session.add(event)
        await self.session.flush()
        return True

    async def list_due_event_ids(self, *, now: datetime, limit: int) -> list[int]:
        statement = (
            select(DepartmentTransferPermissionCleanupEvent.id)
            .where(
                col(DepartmentTransferPermissionCleanupEvent.status).in_(
                    DepartmentTransferCleanupEventStatus.RETRYABLE | {DepartmentTransferCleanupEventStatus.PROCESSING},
                ),
                or_(
                    DepartmentTransferPermissionCleanupEvent.next_retry_at.is_(None),
                    DepartmentTransferPermissionCleanupEvent.next_retry_at <= now,
                ),
            )
            .order_by(
                DepartmentTransferPermissionCleanupEvent.next_retry_at.asc(),
                DepartmentTransferPermissionCleanupEvent.id.asc(),
            )
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return [int(event_id) for event_id in result.scalars().all()]

    async def list_preparing_events(self, *, limit: int) -> list[DepartmentTransferPermissionCleanupEvent]:
        result = await self.session.execute(
            select(DepartmentTransferPermissionCleanupEvent)
            .where(
                DepartmentTransferPermissionCleanupEvent.status == DepartmentTransferCleanupEventStatus.PREPARING,
            )
            .order_by(DepartmentTransferPermissionCleanupEvent.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_active_events_for_user(
        self,
        *,
        user_id: int,
    ) -> list[DepartmentTransferPermissionCleanupEvent]:
        result = await self.session.execute(
            select(DepartmentTransferPermissionCleanupEvent)
            .where(
                DepartmentTransferPermissionCleanupEvent.user_id == user_id,
                ~col(DepartmentTransferPermissionCleanupEvent.status).in_(
                    DepartmentTransferCleanupEventStatus.TERMINAL,
                ),
            )
            .order_by(DepartmentTransferPermissionCleanupEvent.id.asc())
        )
        return list(result.scalars().all())

    async def list_processable_items(
        self,
        *,
        event_id: int,
        limit: int,
    ) -> list[DepartmentTransferPermissionCleanupItem]:
        result = await self.session.execute(
            select(DepartmentTransferPermissionCleanupItem)
            .where(
                DepartmentTransferPermissionCleanupItem.event_id == event_id,
                col(DepartmentTransferPermissionCleanupItem.status).in_(
                    DepartmentTransferCleanupItemStatus.PROCESSABLE,
                ),
            )
            .order_by(DepartmentTransferPermissionCleanupItem.id.asc())
            .limit(limit)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def transition_item(
        self,
        item_id: int,
        *,
        to_status: str,
        processed_at: datetime | None,
        last_error: str | None = None,
    ) -> bool:
        result = await self.session.execute(
            select(DepartmentTransferPermissionCleanupItem)
            .where(DepartmentTransferPermissionCleanupItem.id == item_id)
            .with_for_update()
        )
        item = result.scalars().first()
        if item is None or item.status not in DepartmentTransferCleanupItemStatus.PROCESSABLE:
            return False
        allowed = DepartmentTransferCleanupItemStatus.TERMINAL | {
            DepartmentTransferCleanupItemStatus.FAILED,
        }
        if to_status not in allowed:
            return False
        item.status = to_status
        item.processed_at = processed_at
        item.last_error = self._sanitize_error(last_error)
        if to_status == DepartmentTransferCleanupItemStatus.FAILED:
            item.retry_count += 1
        self.session.add(item)
        await self.session.flush()
        return True

    async def mark_event_failed(
        self,
        event_id: int,
        *,
        error_summary: str,
        next_retry_at: datetime,
    ) -> DepartmentTransferPermissionCleanupEvent | None:
        event = await self._event_for_update(event_id)
        if event is None or event.status in DepartmentTransferCleanupEventStatus.TERMINAL:
            return event
        event.status = (
            DepartmentTransferCleanupEventStatus.OVERDUE
            if event.overdue_at is not None
            else DepartmentTransferCleanupEventStatus.FAILED
        )
        event.last_error = self._sanitize_error(error_summary)
        event.next_retry_at = next_retry_at
        self.session.add(event)
        await self.session.flush()
        return event

    async def mark_event_overdue(self, event_id: int, *, now: datetime) -> bool:
        event = await self._event_for_update(event_id)
        if event is None or event.status in DepartmentTransferCleanupEventStatus.TERMINAL:
            return False
        if event.deadline_at is None or event.deadline_at > now:
            return False
        first_mark = event.overdue_at is None
        event.overdue_at = event.overdue_at or now
        event.status = DepartmentTransferCleanupEventStatus.OVERDUE
        event.next_retry_at = event.next_retry_at or now
        self.session.add(event)
        await self.session.flush()
        return first_mark

    async def mark_event_succeeded(
        self,
        event_id: int,
        *,
        completed_at: datetime,
    ) -> DepartmentTransferPermissionCleanupEvent | None:
        event = await self._event_for_update(event_id)
        if event is None or event.status == DepartmentTransferCleanupEventStatus.CANCELLED:
            return event
        await self.refresh_event_counts(event_id)
        await self.session.refresh(event)
        if event.failed_count:
            return event
        result = await self.session.execute(
            select(func.count(DepartmentTransferPermissionCleanupItem.id)).where(
                DepartmentTransferPermissionCleanupItem.event_id == event_id,
                col(DepartmentTransferPermissionCleanupItem.status).in_(
                    DepartmentTransferCleanupItemStatus.PROCESSABLE,
                ),
            )
        )
        if int(result.scalar_one()) > 0:
            return event
        event.status = DepartmentTransferCleanupEventStatus.SUCCEEDED
        event.completed_at = completed_at
        event.next_retry_at = None
        event.last_error = None
        self.session.add(event)
        await self.session.flush()
        return event

    async def refresh_event_counts(self, event_id: int) -> None:
        result = await self.session.execute(
            select(
                DepartmentTransferPermissionCleanupItem.status,
                func.count(DepartmentTransferPermissionCleanupItem.id),
            )
            .where(DepartmentTransferPermissionCleanupItem.event_id == event_id)
            .group_by(DepartmentTransferPermissionCleanupItem.status)
        )
        counts = {status: int(count) for status, count in result.all()}
        event = await self._event_for_update(event_id)
        if event is None:
            return
        event.total_count = sum(counts.values())
        event.revoked_count = counts.get(DepartmentTransferCleanupItemStatus.REVOKED, 0)
        event.protected_count = counts.get(DepartmentTransferCleanupItemStatus.PROTECTED, 0)
        event.skipped_count = counts.get(DepartmentTransferCleanupItemStatus.SKIPPED, 0)
        event.failed_count = counts.get(DepartmentTransferCleanupItemStatus.FAILED, 0)
        self.session.add(event)
        await self.session.flush()

    async def set_snapshot_complete(self, event_id: int, *, complete: bool, error: str | None = None) -> None:
        event = await self._event_for_update(event_id)
        if event is None:
            return
        event.snapshot_complete = complete
        event.last_error = self._sanitize_error(error)
        self.session.add(event)
        await self.session.flush()

    async def get_item(
        self,
        *,
        event_id: int,
        item_key: str,
    ) -> DepartmentTransferPermissionCleanupItem | None:
        return await self._item_for_update(event_id, item_key)

    async def resolve_resource_contexts(
        self,
        *,
        resources: set[tuple[str, str]],
    ) -> dict[tuple[str, str], dict]:
        from bisheng.knowledge.domain.models.knowledge import Knowledge
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
        from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope

        file_keys = {
            (resource_type, resource_id)
            for resource_type, resource_id in resources
            if resource_type in {"folder", "knowledge_file"} and str(resource_id).isdigit()
        }
        file_ids = [int(resource_id) for _, resource_id in file_keys]
        file_map: dict[int, KnowledgeFile] = {}
        if file_ids:
            result = await self.session.execute(select(KnowledgeFile).where(col(KnowledgeFile.id).in_(file_ids)))
            file_map = {int(row.id): row for row in result.scalars().all()}

        root_space_ids = {
            int(resource_id)
            for resource_type, resource_id in resources
            if resource_type == "knowledge_space" and str(resource_id).isdigit()
        }
        root_space_ids.update(int(row.knowledge_id) for row in file_map.values() if row.knowledge_id is not None)
        knowledge_map: dict[int, Knowledge] = {}
        scope_map: dict[int, KnowledgeSpaceScope] = {}
        if root_space_ids:
            result = await self.session.execute(select(Knowledge).where(col(Knowledge.id).in_(sorted(root_space_ids))))
            knowledge_map = {int(row.id): row for row in result.scalars().all()}
            result = await self.session.execute(
                select(KnowledgeSpaceScope).where(col(KnowledgeSpaceScope.space_id).in_(sorted(root_space_ids)))
            )
            scope_map = {int(row.space_id): row for row in result.scalars().all()}

        contexts: dict[tuple[str, str], dict] = {}
        for resource_type, resource_id in resources:
            root_space_id: int | None = None
            uploader_user_id: int | None = None
            if resource_type == "knowledge_space" and str(resource_id).isdigit():
                root_space_id = int(resource_id)
            elif resource_type in {"folder", "knowledge_file"} and str(resource_id).isdigit():
                file = file_map.get(int(resource_id))
                if file is not None:
                    root_space_id = int(file.knowledge_id)
                    uploader_user_id = int(file.user_id) if file.user_id is not None else None
            if root_space_id is None:
                continue
            knowledge = knowledge_map.get(root_space_id)
            scope = scope_map.get(root_space_id)
            if knowledge is None or scope is None:
                continue
            scope_level = getattr(scope.level, "value", scope.level)
            contexts[(resource_type, str(resource_id))] = {
                "root_space_id": root_space_id,
                "scope_level": str(scope_level),
                "creator_user_id": (int(knowledge.user_id) if knowledge.user_id is not None else None),
                "uploader_user_id": uploader_user_id,
            }
        return contexts

    async def list_active_memberships(self, *, user_id: int) -> list:
        from bisheng.common.models.space_channel_member import (
            BusinessTypeEnum,
            MembershipStatusEnum,
            SpaceChannelMember,
        )

        rows: list[SpaceChannelMember] = []
        offset = 0
        while True:
            result = await self.session.execute(
                select(SpaceChannelMember)
                .where(
                    SpaceChannelMember.user_id == user_id,
                    SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                    SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
                )
                .order_by(SpaceChannelMember.id.asc())
                .offset(offset)
                .limit(100)
            )
            page = list(result.scalars().all())
            rows.extend(page)
            if len(page) < 100:
                break
            offset += len(page)
        return rows

    async def list_active_department_file_grants(
        self,
        *,
        tenant_id: int,
        user_id: int,
    ) -> list:
        from bisheng.knowledge.domain.models.department_file_view_grant import (
            DepartmentFileViewGrant,
            DepartmentFileViewGrantStatus,
        )

        rows: list[DepartmentFileViewGrant] = []
        offset = 0
        while True:
            result = await self.session.execute(
                select(DepartmentFileViewGrant)
                .where(
                    DepartmentFileViewGrant.tenant_id == tenant_id,
                    DepartmentFileViewGrant.user_id == user_id,
                    DepartmentFileViewGrant.status == DepartmentFileViewGrantStatus.ACTIVE,
                )
                .order_by(DepartmentFileViewGrant.id.asc())
                .offset(offset)
                .limit(100)
            )
            page = list(result.scalars().all())
            rows.extend(page)
            if len(page) < 100:
                break
            offset += len(page)
        return rows

    async def remove_membership_snapshot(
        self,
        *,
        member_id: int,
        user_id: int,
        space_id: int,
        expected_source: str,
    ) -> str:
        from bisheng.common.models.space_channel_member import (
            BusinessTypeEnum,
            SpaceChannelMember,
            UserRoleEnum,
        )

        result = await self.session.execute(
            select(SpaceChannelMember)
            .where(
                SpaceChannelMember.id == member_id,
                SpaceChannelMember.user_id == user_id,
                SpaceChannelMember.business_id == str(space_id),
                SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
            )
            .with_for_update()
        )
        member = result.scalars().first()
        if member is None:
            return DepartmentTransferCleanupItemStatus.SKIPPED
        if (
            getattr(member.user_role, "value", member.user_role) == UserRoleEnum.CREATOR.value
            or (member.membership_source or "manual") == "department_admin"
        ):
            return DepartmentTransferCleanupItemStatus.SKIPPED
        if (member.membership_source or "manual") != expected_source:
            return DepartmentTransferCleanupItemStatus.SKIPPED
        await self.session.delete(member)
        await self.session.flush()
        return DepartmentTransferCleanupItemStatus.REVOKED

    async def _event_for_update(
        self,
        event_id: int,
    ) -> DepartmentTransferPermissionCleanupEvent | None:
        result = await self.session.execute(
            select(DepartmentTransferPermissionCleanupEvent)
            .where(DepartmentTransferPermissionCleanupEvent.id == event_id)
            .with_for_update()
        )
        return result.scalars().first()

    async def _item_for_update(
        self,
        event_id: int,
        item_key: str,
    ) -> DepartmentTransferPermissionCleanupItem | None:
        result = await self.session.execute(
            select(DepartmentTransferPermissionCleanupItem)
            .where(
                DepartmentTransferPermissionCleanupItem.event_id == event_id,
                DepartmentTransferPermissionCleanupItem.item_key == item_key,
            )
            .with_for_update()
        )
        return result.scalars().first()

    @staticmethod
    def _sanitize_error(error: str | None) -> str | None:
        if not error:
            return None
        return str(error).replace("\n", " ")[:1000]
