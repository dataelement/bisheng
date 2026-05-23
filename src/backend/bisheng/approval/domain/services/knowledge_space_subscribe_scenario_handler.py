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
            'space_name': req.payload_snapshot.get('space_name') or req.business_name,
        }

    async def build_business_link(self, req) -> dict:
        return {'space_id': req.payload_snapshot.get('space_id')}

    async def resolve_approvers(self, node_config: dict, req) -> list[int]:
        sources = node_config.get('sources') or []
        if not sources:
            approver_ids = node_config.get('approver_user_ids') or node_config.get('user_ids') or []
            return [int(one) for one in approver_ids]

        from bisheng.approval.domain.services.approver_resolver import resolve_approvers_from_sources
        seen: set[int] = set()
        result: list[int] = []

        space_source_types = {'knowledge_space_owner', 'knowledge_space_manager', 'space_admin'}
        has_space_source = any(s.get('type') in space_source_types for s in sources)

        space = None
        space_admins: list[int] = []
        if has_space_source:
            space_id = req.payload_snapshot.get('space_id') or req.business_resource_id
            if space_id:
                try:
                    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
                    from bisheng.common.models.space_channel_member import SpaceChannelMemberDao, UserRoleEnum
                    space = await KnowledgeDao.aquery_by_id(int(space_id))
                    members = await SpaceChannelMemberDao.async_get_members_by_space(
                        int(space_id), user_roles=[UserRoleEnum.CREATOR, UserRoleEnum.ADMIN]
                    )
                    space_admins = [m.user_id for m in members]
                except Exception:
                    logger.exception('resolve_approvers: failed to load space owner/admins for space_id=%s', space_id)

        for source in sources:
            source_type = source.get('type', '')
            if source_type == 'knowledge_space_owner':
                owner_ids: list[int] = []
                if space and space.user_id:
                    owner_ids.append(int(space.user_id))
                # Also include members with CREATOR role as fallback
                for uid in space_admins:
                    if uid not in owner_ids:
                        owner_ids.append(uid)
                for uid in owner_ids:
                    if uid not in seen:
                        seen.add(uid)
                        result.append(uid)
            elif source_type in ('knowledge_space_manager', 'space_admin'):
                for uid in space_admins:
                    if uid not in seen:
                        seen.add(uid)
                        result.append(uid)

        # Resolve generic source types (direct_user, department_admin, tenant_admin)
        generic_sources = [s for s in sources if s.get('type') not in space_source_types]
        if generic_sources:
            generic_ids = await resolve_approvers_from_sources(generic_sources, req)
            for uid in generic_ids:
                if uid not in seen:
                    seen.add(uid)
                    result.append(uid)

        return result

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
