from __future__ import annotations

import logging

from bisheng.common.models.space_channel_member import BusinessTypeEnum, MembershipStatusEnum

logger = logging.getLogger(__name__)


class ChannelSubscribeScenarioHandler:
    scenario_code = 'channel_subscribe_request'

    def __init__(self, space_channel_member_repository):
        self.space_channel_member_repository = space_channel_member_repository

    async def validate(self, req, login_user) -> None:
        return None

    async def build_title(self, req) -> str:
        return req.business_name

    async def build_detail(self, req) -> dict:
        return {
            'channel_id': req.payload_snapshot.get('channel_id'),
            'channel_name': req.payload_snapshot.get('channel_name') or req.business_name,
            'applicant_user_id': req.applicant_user_id,
            'applicant_user_name': req.applicant_user_name,
        }

    async def build_business_link(self, req) -> dict:
        return {'channel_id': req.payload_snapshot.get('channel_id')}

    async def resolve_approvers(self, node_config: dict, req) -> list[int]:
        sources = node_config.get('sources') or []
        if sources:
            from bisheng.approval.domain.services.approver_resolver import resolve_approvers_from_sources
            return await resolve_approvers_from_sources(sources, req)
        approver_ids = node_config.get('approver_user_ids') or node_config.get('user_ids') or []
        return [int(one) for one in approver_ids]

    async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict:
        membership = await self._get_membership(payload_snapshot)
        if not membership:
            logger.warning('Channel membership not found when approval instance=%s approved', instance_id)
            return {'status': 'missing_membership'}
        membership.status = MembershipStatusEnum.ACTIVE
        await self.space_channel_member_repository.update(membership)
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

    async def _get_membership(self, payload_snapshot: dict):
        return await self.space_channel_member_repository.find_membership(
            business_id=str(payload_snapshot['channel_id']),
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=int(payload_snapshot['applicant_user_id']),
        )
