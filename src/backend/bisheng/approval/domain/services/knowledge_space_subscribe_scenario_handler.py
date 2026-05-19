from __future__ import annotations

import logging

from bisheng.common.models.space_channel_member import MembershipStatusEnum

logger = logging.getLogger(__name__)


class KnowledgeSpaceSubscribeScenarioHandler:
    scenario_code = 'knowledge_space_subscribe_request'

    def __init__(self, *, find_member, update_member, sync_permissions):
        self.find_member = find_member
        self.update_member = update_member
        self.sync_permissions = sync_permissions

    async def validate(self, req, login_user) -> None:
        return None

    async def build_title(self, req) -> str:
        return req.business_name

    async def build_detail(self, req) -> dict:
        return {
            'space_id': req.payload_snapshot.get('space_id'),
            'space_name': req.payload_snapshot.get('space_name') or req.business_name,
            'applicant_user_id': req.applicant_user_id,
            'applicant_user_name': req.applicant_user_name,
        }

    async def build_business_link(self, req) -> dict:
        return {'space_id': req.payload_snapshot.get('space_id')}

    async def resolve_approvers(self, node_config: dict, req) -> list[int]:
        approver_ids = node_config.get('approver_user_ids') or node_config.get('user_ids') or []
        return [int(one) for one in approver_ids]

    async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict:
        member = await self.find_member(int(payload_snapshot['space_id']), int(payload_snapshot['applicant_user_id']))
        if not member:
            logger.warning('Knowledge space member not found when approval instance=%s approved', instance_id)
            return {'status': 'missing_membership'}
        member.status = MembershipStatusEnum.ACTIVE
        await self.update_member(member)
        await self.sync_permissions(
            int(payload_snapshot['space_id']),
            member.user_id,
            member.user_role,
            is_active=True,
        )
        return {'status': MembershipStatusEnum.ACTIVE.value}

    async def on_rejected(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        member = await self.find_member(int(payload_snapshot['space_id']), int(payload_snapshot['applicant_user_id']))
        if not member:
            logger.warning('Knowledge space member not found when approval instance=%s rejected', instance_id)
            return
        member.status = MembershipStatusEnum.REJECTED
        await self.update_member(member)

    async def on_withdrawn(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        return None
