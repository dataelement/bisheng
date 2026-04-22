from __future__ import annotations

from bisheng.approval.domain.schemas.approval_schema import ApprovalDecisionActionEnum
from bisheng.approval.domain.services.approval_service import ApprovalService
from bisheng.message.domain.models.inbox_message import InboxMessage
from bisheng.message.domain.services.approval_handler import ApprovalHandler


class DepartmentKnowledgeSpaceUploadApprovalHandler(ApprovalHandler):
    LEGACY_REJECT_REASON = 'Rejected via legacy message approval route'

    def get_action_code(self) -> str:
        return 'request_department_knowledge_space_upload'

    async def on_approved(self, message: InboxMessage, operator_user_id: int) -> None:
        request_id = self._extract_business_id(message.content, 'approval_request_id')
        await ApprovalService.decide_request(
            request_id=int(request_id),
            operator_user_id=operator_user_id,
            action=ApprovalDecisionActionEnum.APPROVE,
            reason=None,
        )

    async def on_rejected(self, message: InboxMessage, operator_user_id: int) -> None:
        request_id = self._extract_business_id(message.content, 'approval_request_id')
        await ApprovalService.decide_request(
            request_id=int(request_id),
            operator_user_id=operator_user_id,
            action=ApprovalDecisionActionEnum.REJECT,
            reason=self.LEGACY_REJECT_REASON,
        )
