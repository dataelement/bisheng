"""分享引用删除后仍保留的审批撤回履历。"""

import logging

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import ApprovalActionLog
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

logger = logging.getLogger(__name__)
SHARE_SCENARIO = "knowledge_space_file_share_request"
SHARE_REVOKED_ACTION = "share_revoked"


class KnowledgeFileShareHistoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def revoked(self, *, tenant_id: int, instance_id: int) -> ApprovalActionLog | None:
        if instance_id <= 0:
            return None
        instance = await ApprovalInstanceRepository.get_instance(instance_id, session=self.session)
        if instance is None:
            return None
        if int(instance.tenant_id) != tenant_id or instance.scenario_code != SHARE_SCENARIO:
            raise ValueError("share approval identity mismatch")
        return await ApprovalInstanceRepository.find_action_log(instance_id, SHARE_REVOKED_ACTION, session=self.session)

    async def record(
        self,
        *,
        tenant_id: int,
        instance_id: int | None,
        document_id: int,
        share_entry_id: int,
        target_space_id: int,
        actor_entry_id: int,
        operator_user_id: int | None,
        operator_user_name: str | None,
    ) -> None:
        if not instance_id or instance_id <= 0:
            logger.warning("Legacy share has no approval history key: entry_id=%s", share_entry_id)
            return
        instance = await ApprovalInstanceRepository.get_instance(instance_id, session=self.session, for_update=True)
        if instance is None:
            # 不为历史缺失实例伪造审批。缺失也不能阻止已授权的停用。
            logger.warning("Share approval history is missing: instance_id=%s entry_id=%s", instance_id, share_entry_id)
            return
        payload = instance.payload_snapshot or {}
        if (
            int(instance.tenant_id) != tenant_id
            or instance.scenario_code != SHARE_SCENARIO
            or int(payload.get("canonical_document_id") or 0) != document_id
            or int(payload.get("target_space_id") or 0) != target_space_id
        ):
            raise ValueError("share approval identity mismatch")
        existing = await ApprovalInstanceRepository.find_action_log(
            instance_id, SHARE_REVOKED_ACTION, session=self.session
        )
        if existing is not None:
            if int(existing.detail.get("share_entry_id") or 0) != share_entry_id:
                raise ValueError("share revocation belongs to another entry")
            return
        await ApprovalInstanceRepository.create_action_log(
            ApprovalActionLog(
                tenant_id=tenant_id,
                instance_id=instance_id,
                action=SHARE_REVOKED_ACTION,
                operator_user_id=operator_user_id,
                operator_user_name=operator_user_name or "系统清理",
                detail={
                    "document_id": document_id,
                    "share_entry_id": share_entry_id,
                    "target_space_id": target_space_id,
                    "actor_entry_id": actor_entry_id,
                    "reason": "接收方移除分享" if actor_entry_id == share_entry_id else "分享方撤回分享",
                },
            ),
            session=self.session,
        )
