"""平台超管在专家问答违规删除：先删内容，再扣分（失败入补扣队列）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.points.domain.services.points_auth import require_platform_admin
from bisheng.points.domain.services.points_pending_deduct_service import PointsPendingDeductService
from bisheng.qa_expert.domain.repositories import (
    AnswerRepository,
    CommentRepository,
    ExpertRepository,
    QuestionRepository,
)
from bisheng.qa_expert.domain.services import (
    AnswerNotFoundError,
    ExpertNotFoundError,
    PermissionDeniedError,
    QuestionNotFoundError,
)
from bisheng.telemetry.domain.mid_table.realtime_qa_question import RealtimeQaQuestionFact

logger = logging.getLogger(__name__)

TargetType = Literal["question", "answer", "comment"]

# qa_answer.status: 1=normal, 2=adopted, 3=deleted
_ANSWER_STATUS_DELETED = 3


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
        self.answer_repo = AnswerRepository()
        self.comment_repo = CommentRepository()
        self.expert_repo = ExpertRepository()
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
        """删除问题、回答或评论/追问；若传入启用中的 R* 则对内容作者扣分。

        未选规则 = 只删不扣。扣分失败不回滚删除, 写入 point_pending_deduct 供 Beat 补扣.
        删回答时级联硬删其下评论，扣分仅针对回答作者。
        """
        require_platform_admin(operator)
        if target_type not in ("question", "answer", "comment"):
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
            return await self._delete_question(target_id)
        if target_type == "answer":
            return await self._delete_answer(target_id)

        comment = await self.comment_repo.get_by_id(target_id)
        if not comment:
            raise AnswerNotFoundError(message="Comment not found")
        author_id = int(comment.user_id)
        deleted = await self.comment_repo.delete(target_id)
        if not deleted:
            raise AnswerNotFoundError(message="Comment not found")
        return author_id, "qa_comment", str(target_id)

    async def _delete_question(self, target_id: int) -> tuple[int, str, str]:
        """硬删问题并清理 telemetry 事实表。"""
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

    async def _delete_answer(self, target_id: int) -> tuple[int, str, str]:
        """软删回答：解析专家作者、级联评论、维护问题计数与最佳答案指针。"""
        answer = await self.answer_repo.get_by_id(target_id)
        if not answer or int(getattr(answer, "status", 0) or 0) == _ANSWER_STATUS_DELETED:
            raise AnswerNotFoundError()

        if not getattr(answer, "expert_id", None):
            raise ExpertNotFoundError(message="Answer has no expert author")
        expert = await self.expert_repo.get_by_id(int(answer.expert_id))
        if expert is None or getattr(expert, "user_id", None) is None:
            raise ExpertNotFoundError(message="Answer expert not found")
        author_id = int(expert.user_id)

        question_id = int(answer.question_id)
        deleted = await self.answer_repo.delete(target_id)
        if not deleted:
            raise AnswerNotFoundError()

        # 级联硬删该回答下评论；不对评论作者逐条扣分
        await self.comment_repo.delete_by_answer_id(target_id)

        question = await self.question_repo.get_by_id(question_id)
        if question is not None:
            next_count = max(0, int(question.answer_count or 0) - 1)
            update_kwargs: dict = {"answer_count": next_count}
            # 删掉最佳答案时回退为未解决，避免详情脏指针
            if int(question.adopted_answer_id or 0) == target_id:
                update_kwargs["adopted_answer_id"] = None
                update_kwargs["status"] = 0
            await self.question_repo.update(question_id, **update_kwargs)

        return author_id, "qa_answer", str(target_id)
