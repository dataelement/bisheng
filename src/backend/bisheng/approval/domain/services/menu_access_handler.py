from __future__ import annotations

from bisheng.approval.domain.services.user_menu_access_service import UserMenuAccessService


class MenuAccessApprovalHandler:
    scenario_code = 'menu_access_request'

    async def validate(self, req, login_user) -> None:
        return None

    async def build_title(self, req) -> str:
        return req.payload_snapshot.get('menu_name') or req.business_name

    async def build_detail(self, req) -> dict:
        return {
            'menu_key': req.payload_snapshot.get('menu_key'),
            'menu_name': req.payload_snapshot.get('menu_name') or req.business_name,
            'reason': req.reason,
        }

    async def build_business_link(self, req) -> dict:
        return {'menu_key': req.payload_snapshot.get('menu_key')}

    async def resolve_approvers(self, node_config: dict, req) -> list[int]:
        approver_ids = node_config.get('approver_user_ids') or node_config.get('user_ids') or []
        return [int(one) for one in approver_ids]

    async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict:
        rows = await UserMenuAccessService.grant_menu_access(
            tenant_id=int(payload_snapshot['tenant_id']),
            user_id=int(payload_snapshot['applicant_user_id']),
            menu_key=str(payload_snapshot['menu_key']),
            menu_name=payload_snapshot.get('menu_name'),
            grant_source='approval_instance',
            grant_instance_id=instance_id,
        )
        return {'granted_keys': [row.menu_key for row in rows]}

    async def on_rejected(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        return None

    async def on_withdrawn(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        return None
