from __future__ import annotations

import logging

from bisheng.common.models.space_channel_member import BusinessTypeEnum, MembershipStatusEnum

logger = logging.getLogger(__name__)


class ChannelSubscribeScenarioHandler:
    scenario_code = 'channel_subscribe_request'

    def __init__(self, space_channel_member_repository, sync_permissions=None):
        self.space_channel_member_repository = space_channel_member_repository
        self.sync_permissions = sync_permissions

    async def validate(self, req, login_user) -> None:
        return None

    async def build_title(self, req) -> str:
        return req.business_name

    async def build_detail(self, req) -> dict:
        return {
            'channel_name': req.payload_snapshot.get('channel_name') or req.business_name,
        }

    async def build_business_link(self, req) -> dict:
        return {'channel_id': req.payload_snapshot.get('channel_id')}

    async def resolve_approvers(self, node_config: dict, req) -> list[int]:
        sources = node_config.get('sources') or []
        if not sources:
            approver_ids = node_config.get('approver_user_ids') or node_config.get('user_ids') or []
            return [int(one) for one in approver_ids]

        from bisheng.approval.domain.services.approver_resolver import resolve_approvers_from_sources
        from bisheng.common.models.space_channel_member import UserRoleEnum

        channel_source_types = {'channel_admin', 'channel_owner', 'channel_manager'}
        has_channel_source = any(s.get('type') in channel_source_types for s in sources)

        channel_admin_ids: list[int] = []
        if has_channel_source:
            channel_id = req.payload_snapshot.get('channel_id') or req.business_resource_id
            if channel_id:
                try:
                    creators = await self.space_channel_member_repository.find_members_by_role(
                        channel_id=str(channel_id), role=UserRoleEnum.CREATOR,
                    )
                    admins = await self.space_channel_member_repository.find_members_by_role(
                        channel_id=str(channel_id), role=UserRoleEnum.ADMIN,
                    )
                    seen_admin: set[int] = set()
                    for m in creators + admins:
                        if m.user_id not in seen_admin:
                            seen_admin.add(m.user_id)
                            channel_admin_ids.append(m.user_id)
                except Exception:
                    logger.exception('resolve_approvers: failed to load channel admins for channel_id=%s', channel_id)

        seen: set[int] = set()
        result: list[int] = []

        for source in sources:
            source_type = source.get('type', '')
            if source_type in channel_source_types:
                for uid in channel_admin_ids:
                    if uid not in seen:
                        seen.add(uid)
                        result.append(uid)

        generic_sources = [s for s in sources if s.get('type') not in channel_source_types]
        if generic_sources:
            generic_ids = await resolve_approvers_from_sources(generic_sources, req)
            for uid in generic_ids:
                if uid not in seen:
                    seen.add(uid)
                    result.append(uid)

        return result

    async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict:
        membership = await self._get_membership(payload_snapshot)
        if not membership:
            logger.warning('Channel membership not found when approval instance=%s approved', instance_id)
            return {'status': 'missing_membership'}
        membership.status = MembershipStatusEnum.ACTIVE
        await self.space_channel_member_repository.update(membership)
        if self.sync_permissions:
            await self.sync_permissions(
                str(payload_snapshot['channel_id']),
                membership.user_id,
                membership.user_role,
                is_active=True,
            )
        return {'status': MembershipStatusEnum.ACTIVE.value}

    async def on_rejected(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        membership = await self._get_membership(payload_snapshot)
        if not membership:
            logger.warning('Channel membership not found when approval instance=%s rejected', instance_id)
            return
        membership.status = MembershipStatusEnum.REJECTED
        await self.space_channel_member_repository.update(membership)

    async def on_withdrawn(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        return None

    async def on_cancelled(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        membership = await self._get_membership(payload_snapshot)
        if not membership:
            return
        membership.status = MembershipStatusEnum.REJECTED
        await self.space_channel_member_repository.update(membership)

    async def _get_membership(self, payload_snapshot: dict):
        return await self.space_channel_member_repository.find_membership(
            business_id=str(payload_snapshot['channel_id']),
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=int(payload_snapshot['applicant_user_id']),
        )
