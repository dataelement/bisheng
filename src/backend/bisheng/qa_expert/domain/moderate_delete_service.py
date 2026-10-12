# ruff: noqa: RUF002, RUF003
"""平台超管在专家问答违规删除：先删内容，再扣分（失败入补扣队列）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from bisheng.common.errcode.points import PointsPermissionDeniedError
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.points.domain.services.points_auth import is_platform_super_admin
from bisheng.points.domain.services.points_pending_deduct_service import PointsPendingDeductService
from bisheng.qa_expert.domain.repositories import (
    AnswerAdoptRepository,
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
        self.adopt_repo = AnswerAdoptRepository()
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

        未选规则 = 只删不扣。作者即操作人（超管删自己）强制不扣。
        扣分失败不回滚删除, 写入 point_pending_deduct 供 Beat 补扣.
        删回答时级联硬删其下评论，扣分仅针对回答作者。
        """
        if not is_platform_super_admin(operator):
            raise PointsPermissionDeniedError()
        if target_type not in ("question", "answer", "comment"):
            raise PermissionDeniedError(message="unsupported target_type")
        if int(target_id) <= 0:
            raise QuestionNotFoundError()

        author_id, biz_type, biz_id = await self._resolve_and_delete(target_type, int(target_id))
        operator_id = int(getattr(operator, "user_id", 0) or 0)
        # 超管删自己的内容：不参与积分排行，强制不扣，避免误选 R* 写脏账本。
        if operator_id and int(author_id) == operator_id:
            return ModerateDeleteResult(
                deleted=True,
                target_type=target_type,
                target_id=int(target_id),
                target_user_id=author_id,
                deducted=False,
                pending_deduct=False,
                reason="self_author",
            )
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

    async def _resolve_and_delete(self, target_type: TargetType, target_id: int) -> tuple[int, str, str]:
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
        """软删回答, 并回退问题概况用的回答数和采纳数.

        Args:
            target_id: qa_answer.id.

        Returns:
            作者用户 id, 业务类型 qa_answer, 以及回答 id 字符串.

        Raises:
            AnswerNotFoundError: 回答不存在或已软删.
            ExpertNotFoundError: 回答没有可解析的专家作者.
        """
        answer = await self.answer_repo.get_by_id(target_id)
        if not answer or int(getattr(answer, "status", 0) or 0) == _ANSWER_STATUS_DELETED:
            raise AnswerNotFoundError()

        if not getattr(answer, "expert_id", None):
            raise ExpertNotFoundError(message="Answer has no expert author")
        expert = await self.expert_repo.get_by_id(int(answer.expert_id))
        if expert is None or getattr(expert, "user_id", None) is None:
            raise ExpertNotFoundError(message="Answer expert not found")
        author_id = int(expert.user_id)
        # 详情状态看 adopt_count, 不是只看 adopted_answer_id. 先记下再软删.
        was_adopted = bool(getattr(answer, "adopted", False)) or int(getattr(answer, "status", 1) or 0) == 2

        question_id = int(answer.question_id)
        deleted = await self.answer_repo.delete(target_id)
        if not deleted:
            raise AnswerNotFoundError()

        # 级联硬删该回答下评论；不对评论作者逐条扣分
        await self.comment_repo.delete_by_answer_id(target_id)
        if was_adopted:
            await self.adopt_repo.delete_by_answer_id(target_id)

        question = await self.question_repo.get_by_id(question_id)
        if question is not None:
            next_answer_count = max(0, int(question.answer_count or 0) - 1)
            next_adopt = int(getattr(question, "adopt_count", 0) or 0)
            if was_adopted:
                next_adopt = max(0, next_adopt - 1)
            update_kwargs: dict = {"answer_count": next_answer_count}
            if was_adopted:
                update_kwargs["adopt_count"] = next_adopt
            pointer_hit = int(question.adopted_answer_id or 0) == target_id
            # 采纳数归零后指针必须清空, 否则详情仍可能显示已解决
            if next_adopt == 0 and (was_adopted or pointer_hit):
                update_kwargs["adopted_answer_id"] = None
                update_kwargs["status"] = 0
            elif pointer_hit:
                update_kwargs["adopted_answer_id"] = await self.answer_repo.latest_active_adopted_id(question_id)
            await self.question_repo.update(question_id, **update_kwargs)

        if was_adopted:
            await self.expert_repo.increment_adoption_count(int(expert.id), count=-1)
        # 软删后回退专家累计回答数, 与作者自删路径同一不变量
        await self.expert_repo.increment_answer_count(int(expert.id), count=-1)

        return author_id, "qa_answer", str(target_id)
