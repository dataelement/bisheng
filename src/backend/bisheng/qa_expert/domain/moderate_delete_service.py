"""平台超管在专家问答违规删除：先删内容，再扣分（失败入补扣队列）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.points.domain.services.points_auth import require_platform_admin
from bisheng.points.domain.services.points_pending_deduct_service import PointsPendingDeductService
from bisheng.qa_expert.domain.repositories import CommentRepository, QuestionRepository
from bisheng.qa_expert.domain.services import (
    AnswerNotFoundError,
    PermissionDeniedError,
    QuestionNotFoundError,
)
from bisheng.telemetry.domain.mid_table.realtime_qa_question import RealtimeQaQuestionFact

logger = logging.getLogger(__name__)

TargetType = Literal["question", "comment"]


@dataclass(frozen=True)
class ModerateDeleteResult:
    """违规删除结果。"""

    deleted: bool
    target_type: str
    target_id: int
    target_user_id: int
    deducted: bool
    pending_deduct: bool
    reason: str | None = None


class ModerateDeleteService:
    """专家问答违规删除编排：鉴权 → 删内容 → 扣分/补扣。"""

    def __init__(self):
        self.question_repo = QuestionRepository()
        self.comment_repo = CommentRepository()
        self.pending_deduct = PointsPendingDeductService()

    async def moderate_delete(
        self,
        *,
        operator,
        target_type: TargetType,
        target_id: int,
        rule_code: str | None = None,
        remark: str | None = None,
    ) -> ModerateDeleteResult:
        """删除问题或评论/追问；若传入启用中的 R* 则对内容作者扣分。

        未选规则 = 只删不扣。扣分失败不回滚删除, 写入 point_pending_deduct 供 Beat 补扣.
        """
        require_platform_admin(operator)
        if target_type not in ("question", "comment"):
            raise PermissionDeniedError(message="unsupported target_type")
        if int(target_id) <= 0:
            raise QuestionNotFoundError()

        author_id, biz_type, biz_id = await self._resolve_and_delete(target_type, int(target_id))
        code = (rule_code or "").strip().upper()
        if not code:
            return ModerateDeleteResult(
                deleted=True,
                target_type=target_type,
                target_id=int(target_id),
                target_user_id=author_id,
                deducted=False,
                pending_deduct=False,
                reason="no_rule",
            )

        tenant_id = int(get_current_tenant_id() or DEFAULT_TENANT_ID)
        attempt = await self.pending_deduct.deduct_or_enqueue(
            tenant_id=tenant_id,
            user_id=author_id,
            rule_code=code,
            biz_type=biz_type,
            biz_id=biz_id,
            operator_id=int(operator.user_id),
            remark=remark,
        )
        return ModerateDeleteResult(
            deleted=True,
            target_type=target_type,
            target_id=int(target_id),
            target_user_id=author_id,
            deducted=attempt.applied,
            pending_deduct=attempt.pending,
            reason=attempt.reason,
        )

    async def _resolve_and_delete(
        self, target_type: TargetType, target_id: int
    ) -> tuple[int, str, str]:
        """解析作者并删除, 返回 (author_user_id, biz_type, biz_id)."""
        if target_type == "question":
            question = await self.question_repo.get_by_id(target_id)
            if not question:
                raise QuestionNotFoundError()
            author_id = int(question.user_id)
            deleted = await self.question_repo.delete(target_id)
            if not deleted:
                raise QuestionNotFoundError()
            try:
                await RealtimeQaQuestionFact.delete_question(
                    tenant_id=int(get_current_tenant_id() or DEFAULT_TENANT_ID),
                    question_id=target_id,
                    qa_type="expert",
                )
            except Exception:
                logger.exception("qa.moderate_delete.telemetry_failed question_id=%s", target_id)
            return author_id, "qa_question", str(target_id)

        comment = await self.comment_repo.get_by_id(target_id)
        if not comment:
            raise AnswerNotFoundError(message="Comment not found")
        author_id = int(comment.user_id)
        deleted = await self.comment_repo.delete(target_id)
        if not deleted:
            raise AnswerNotFoundError(message="Comment not found")
        return author_id, "qa_comment", str(target_id)
