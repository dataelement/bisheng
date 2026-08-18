# ruff: noqa: RUF002, RUF003
"""定向题转公开：申请、审批、专家停用默认同意、到期过期。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from loguru import logger

from bisheng.common.errcode.qa_expert import (
    QaExpertPublishConflictError,
    QaExpertPublishDurationInvalidError,
    QaExpertPublishNotAllowedError,
    QaExpertQuestionAccessDeniedError,
)
from bisheng.common.utils.beijing_time import now_beijing, to_beijing_iso
from bisheng.database.models.qa_expert import (
    QUESTION_TYPE_PUBLIC,
    AnswerEligibility,
    PublishApprover,
    PublishRequest,
)
from bisheng.qa_expert.domain.capability import (
    CapabilityResolver,
    CapabilitySnapshot,
)
from bisheng.qa_expert.domain.repositories import (
    AnswerEligibilityRepository,
    AnswerRepository,
    ExpertRepository,
    PublishApproverRepository,
    PublishRequestRepository,
    QuestionInviteRepository,
    QuestionRepository,
)

ALLOWED_DURATION_DAYS = frozenset({1, 3, 7})
MAX_EXTENSION_DAYS = 3
PUBLISH_PENDING = "pending"
PUBLISH_APPROVED = "approved"
PUBLISH_REJECTED = "rejected"
PUBLISH_EXPIRED = "expired"
PUBLISH_ENDED = "ended"
DECISION_PENDING = "pending"
DECISION_APPROVED = "approved"
DECISION_REJECTED = "rejected"
DECISION_DEFAULT_APPROVED = "default_approved"
ROLE_ASKER = "asker"
ROLE_ANSWERER = "answerer"
ANSWER_STATUS_DELETED = 3
ELIGIBILITY_INVITED = "invited"
ELIGIBILITY_ANSWER = "pre_adopt_answer"


def serialize_publish_request(
    row: PublishRequest,
    *,
    viewer_decision: str | None = None,
) -> dict[str, Any]:
    """详情挂载用的转公开申请摘要。

    viewer_decision 是当前登录用户在 qa_publish_approver 上的决策；
    发起人创建时已默认同意，详情右上角据此展示「已同意」。
    """
    expire_at = getattr(row, "expire_at", None)
    return {
        "id": int(row.id),
        "status": str(row.status),
        "duration_days": int(getattr(row, "duration_days", 0) or 0),
        "expire_at": to_beijing_iso(expire_at) if expire_at is not None else None,
        "extension_days": int(getattr(row, "extension_days", 0) or 0),
        "viewer_decision": viewer_decision,
    }


class PublishService:
    """转公开申请编排；通过后 question_type=public，并补写回答资格快照。"""

    def __init__(self):
        self.question_repo = QuestionRepository()
        self.answer_repo = AnswerRepository()
        self.invite_repo = QuestionInviteRepository()
        self.expert_repo = ExpertRepository()
        self.request_repo = PublishRequestRepository()
        self.approver_repo = PublishApproverRepository()
        self.eligibility_repo = AnswerEligibilityRepository()
        self.capability_resolver = CapabilityResolver()
        self.notify = None  # 测试可注入 async (event, question, extra)

    async def create_publish_request(
        self,
        question_id: int,
        user,
        duration_days: int,
        *,
        now: datetime | None = None,
    ) -> PublishRequest:
        """发起转公开；有效期仅 1/3/7；同题至多一条 pending。"""
        if int(duration_days) not in ALLOWED_DURATION_DAYS:
            raise QaExpertPublishDurationInvalidError()
        if user is None or getattr(user, "user_id", None) is None:
            raise QaExpertQuestionAccessDeniedError()
        now = now or now_beijing()
        question = await self.question_repo.get_by_id_for_update(question_id)
        if not question:
            from bisheng.qa_expert.domain.services import QuestionNotFoundError

            raise QuestionNotFoundError()
        if await self.request_repo.get_pending_by_question(question_id):
            raise QaExpertPublishConflictError()
        snapshot = await self._snapshot(question, user, has_pending=False)
        caps = self.capability_resolver.resolve(user, question, snapshot).capabilities
        if not caps.can_start_publish:
            raise QaExpertPublishNotAllowedError()

        tenant_id = int(getattr(question, "tenant_id", 1) or 1)
        request = PublishRequest(
            tenant_id=tenant_id,
            question_id=int(question.id),
            initiator_user_id=int(user.user_id),
            status=PUBLISH_PENDING,
            duration_days=int(duration_days),
            expire_at=now + timedelta(days=int(duration_days)),
            extension_days=0,
            version=0,
        )
        request = await self.request_repo.create(request)
        approvers = await self._build_approvers(question, request, user, now)
        await self.approver_repo.create_many(approvers)
        await self.question_repo.update(int(question.id), active_publish_request_id=request.id)
        from bisheng.qa_expert.domain.publish_approval_bridge import sync_after_create

        await sync_after_create(request, question, user, approvers)
        await self._notify("publish_started", question, extra={"request_id": request.id, "user": user})
        finalized = await self._maybe_finalize(request, question, now=now)
        await self._sync_approval_center(finalized)
        refreshed = await self.request_repo.get_by_id(int(request.id))
        return refreshed or request

    async def decide_publish(
        self,
        request_id: int,
        user,
        decision: str,
        *,
        now: datetime | None = None,
    ) -> PublishRequest:
        """同意或拒绝；已决策不可改口。"""
        now = now or now_beijing()
        if user is None or getattr(user, "user_id", None) is None:
            raise QaExpertQuestionAccessDeniedError()
        request = await self._get_live_request(request_id, now=now)
        if request.status != PUBLISH_PENDING:
            raise QaExpertPublishNotAllowedError()
        row = await self.approver_repo.get_for_user(int(request.id), int(user.user_id))
        if row is None:
            raise QaExpertPublishNotAllowedError()
        if str(row.decision) != DECISION_PENDING:
            raise QaExpertPublishNotAllowedError()
        normalized = str(decision or "").strip().lower()
        if normalized not in {DECISION_APPROVED, DECISION_REJECTED}:
            raise QaExpertPublishNotAllowedError()
        await self.approver_repo.update(int(row.id), decision=normalized, decided_at=now)
        question = await self.question_repo.get_by_id(int(request.question_id))
        if not question:
            from bisheng.qa_expert.domain.services import QuestionNotFoundError

            raise QuestionNotFoundError()
        if normalized == DECISION_REJECTED:
            await self._close_request(request, PUBLISH_REJECTED, question)
            await self._notify("publish_rejected", question, extra={"request_id": request.id, "user": user})
            request.status = PUBLISH_REJECTED
            await self._sync_approval_center(request)
            return request
        result = await self._maybe_finalize(request, question, now=now)
        await self._sync_approval_center(result)
        return result

    async def on_expert_disabled(self, user_id: int, *, now: datetime | None = None) -> list[int]:
        """停用专家：pending 审批改 default_approved，立即重判；不加入已结束申请。"""
        now = now or now_beijing()
        passed: list[int] = []
        # 通过仓储列出该用户仍 pending 的审批行：由调用方注入 list_pending_for_user
        list_pending = getattr(self.approver_repo, "list_pending_for_user", None)
        rows = await list_pending(int(user_id)) if callable(list_pending) else []
        for row in rows:
            request = await self.request_repo.get_by_id(int(row.request_id))
            if request is None or request.status != PUBLISH_PENDING:
                continue
            await self.approver_repo.update(
                int(row.id),
                decision=DECISION_DEFAULT_APPROVED,
                decided_at=now,
            )
            question = await self.question_repo.get_by_id(int(request.question_id))
            if question is None:
                continue
            finalized = await self._maybe_finalize(request, question, now=now)
            if finalized.status == PUBLISH_APPROVED:
                passed.append(int(finalized.id))
                await self._notify(
                    "publish_default_approved",
                    question,
                    extra={"request_id": request.id, "disabled_user_id": user_id},
                )
            await self._sync_approval_center(finalized)
        return passed

    async def on_asker_disabled(self, question_id: int, *, now: datetime | None = None) -> PublishRequest | None:
        """提问者账号停用：进行中的申请 ended。"""
        now = now or now_beijing()
        request = await self.request_repo.get_pending_by_question(int(question_id))
        if request is None:
            return None
        question = await self.question_repo.get_by_id(int(question_id))
        if question is None:
            return request
        await self._close_request(request, PUBLISH_ENDED, question)
        await self._notify("publish_ended", question, extra={"request_id": request.id})
        request.status = PUBLISH_ENDED
        await self._sync_approval_center(request)
        return request

    async def refresh_latest_for_question(
        self, question_id: int, *, now: datetime | None = None
    ) -> PublishRequest | None:
        """读详情前惰性过期，再返回同题最近一条申请。"""
        now = now or now_beijing()
        pending = await self.request_repo.get_pending_by_question(int(question_id))
        if pending is not None and pending.expire_at is not None and pending.expire_at <= now:
            await self._get_live_request(int(pending.id), now=now)
        return await self.request_repo.get_latest_by_question(int(question_id))

    async def extend_one_day(self, request_id: int, user, *, now: datetime | None = None) -> PublishRequest:
        """+1 天延期，累计不超过 3 天。"""
        now = now or now_beijing()
        request = await self._get_live_request(request_id, now=now)
        if request.status != PUBLISH_PENDING:
            raise QaExpertPublishNotAllowedError()
        if int(request.extension_days or 0) >= MAX_EXTENSION_DAYS:
            raise QaExpertPublishDurationInvalidError()
        return await self._bump_expire_one_day(request)

    async def _bump_expire_one_day(self, request: PublishRequest) -> PublishRequest:
        """把 expire_at 往后推 1 天并记 extension_days；调用方已保证未达上限。"""
        new_ext = int(request.extension_days or 0) + 1
        expire_at = request.expire_at
        if expire_at is None:
            return request
        updated = await self.request_repo.update(
            int(request.id),
            extension_days=new_ext,
            expire_at=expire_at + timedelta(days=1),
            version=int(request.version or 0) + 1,
        )
        return updated or request

    async def _try_extend_for_late_answerer(self, request: PublishRequest) -> PublishRequest:
        """中途新会签人：截止 +1 天，累计不超过 3 天；已满则只加人、不改时间。"""
        if str(request.status) != PUBLISH_PENDING:
            return request
        if int(request.extension_days or 0) >= MAX_EXTENSION_DAYS:
            return request
        return await self._bump_expire_one_day(request)

    async def expire_pending(self, *, now: datetime | None = None, tenant_id: int | None = None) -> int:
        """把到期 pending 标为 expired，并通知。tenant_id 仅记录上下文。"""
        now = now or now_beijing()
        rows = await self.request_repo.list_expired_pending(now)
        count = 0
        for request in rows:
            if tenant_id is not None and int(getattr(request, "tenant_id", 0) or 0) != int(tenant_id):
                continue
            question = await self.question_repo.get_by_id(int(request.question_id))
            if question is None:
                continue
            await self._close_request(request, PUBLISH_EXPIRED, question)
            await self._notify("publish_expired", question, extra={"request_id": request.id})
            request.status = PUBLISH_EXPIRED
            await self._sync_approval_center(request)
            count += 1
        return count

    async def get_request(self, request_id: int, user, *, now: datetime | None = None) -> PublishRequest:
        """读取申请；读路径顺带惰性过期。"""
        return await self._get_live_request(request_id, now=now or now_beijing())

    async def _get_live_request(self, request_id: int, *, now: datetime) -> PublishRequest:
        request = await self.request_repo.get_by_id(int(request_id))
        if request is None:
            from bisheng.qa_expert.domain.services import QuestionNotFoundError

            raise QuestionNotFoundError()
        if request.status == PUBLISH_PENDING and request.expire_at <= now:
            question = await self.question_repo.get_by_id(int(request.question_id))
            if question is not None:
                await self._close_request(request, PUBLISH_EXPIRED, question)
                await self._notify("publish_expired", question, extra={"request_id": request.id})
            request.status = PUBLISH_EXPIRED
            await self._sync_approval_center(request)
        return request

    async def _snapshot(self, question, user, *, has_pending: bool | None = None) -> CapabilitySnapshot:
        invite_map = await self.invite_repo.list_user_ids_by_question_ids([int(question.id)])
        invited = invite_map.get(int(question.id), set())
        uid = int(user.user_id)
        expert = await self.expert_repo.get_by_user_id(uid)
        has_answer = await self.answer_repo.has_effective_answer(int(question.id), uid)
        pending = await self.request_repo.get_pending_by_question(int(question.id))
        pending_flag = pending is not None if has_pending is None else has_pending
        latest = pending or await self.request_repo.get_latest_by_question(int(question.id))
        approver_ids: set[int] = set()
        viewer_decision: str | None = None
        source = pending if pending is not None else latest
        if source is not None:
            for row in await self.approver_repo.list_by_request(int(source.id)):
                if int(row.user_id) == uid:
                    viewer_decision = str(row.decision)
                # 已决策的人（含发起人默认同意）不再出现同意/拒绝按钮。
                if pending is not None and str(row.decision) == DECISION_PENDING:
                    approver_ids.add(int(row.user_id))
        return CapabilitySnapshot(
            expert=expert,
            invited_user_ids=frozenset(invited),
            effective_answer_count=int(getattr(question, "answer_count", 0) or 0),
            user_has_effective_answer=has_answer,
            has_pending_publish=pending_flag,
            latest_publish_status=str(latest.status) if latest is not None else None,
            approver_user_ids=frozenset(approver_ids),
            viewer_publish_decision=viewer_decision,
        )

    async def _build_approvers(
        self,
        question,
        request: PublishRequest,
        initiator,
        now: datetime,
    ) -> list[PublishApprover]:
        """组装会签人：提问者 + 有效回答专家；发起人对应行默认 approved。"""
        tenant_id = int(getattr(question, "tenant_id", 1) or 1)
        asker_id = int(question.user_id)
        initiator_id = int(initiator.user_id)
        answers = await self.answer_repo.list_all_by_question_id(int(question.id))
        answerer_ids: list[int] = []
        seen: set[int] = set()
        for answer in answers:
            if int(getattr(answer, "status", 1) or 0) == ANSWER_STATUS_DELETED:
                continue
            uid = getattr(answer, "user_id", None)
            if uid is None:
                continue
            uid = int(uid)
            if uid in seen or uid == asker_id:
                continue
            seen.add(uid)
            answerer_ids.append(uid)
        # 谁发起谁默认同意：提问者发起则 asker 行直接 approved，回答专家发起则该专家行直接 approved。
        rows: list[PublishApprover] = []
        rows.append(
            PublishApprover(
                tenant_id=tenant_id,
                request_id=int(request.id),
                user_id=asker_id,
                role_in_request=ROLE_ASKER,
                decision=DECISION_APPROVED if initiator_id == asker_id else DECISION_PENDING,
                decided_at=now if initiator_id == asker_id else None,
            )
        )
        for uid in answerer_ids:
            auto = uid == initiator_id
            rows.append(
                PublishApprover(
                    tenant_id=tenant_id,
                    request_id=int(request.id),
                    user_id=uid,
                    role_in_request=ROLE_ANSWERER,
                    decision=DECISION_APPROVED if auto else DECISION_PENDING,
                    decided_at=now if auto else None,
                )
            )
        return rows

    async def _maybe_finalize(self, request: PublishRequest, question, *, now: datetime) -> PublishRequest:
        approvers = await self.approver_repo.list_by_request(int(request.id))
        if any(str(row.decision) == DECISION_PENDING for row in approvers):
            return request
        if any(str(row.decision) == DECISION_REJECTED for row in approvers):
            await self._close_request(request, PUBLISH_REJECTED, question)
            request.status = PUBLISH_REJECTED
            return request
        await self._approve_question(request, question)
        await self._notify("publish_approved", question, extra={"request_id": request.id})
        request.status = PUBLISH_APPROVED
        return request

    async def add_late_answerer(self, question, user_id: int) -> None:
        """pending 转公开期间新回答的受邀专家加入会签，并补待办。"""
        request = await self.request_repo.get_pending_by_question(int(question.id))
        if request is None:
            return
        existing = await self.approver_repo.get_for_user(int(request.id), int(user_id))
        if existing is not None:
            return
        row = PublishApprover(
            tenant_id=int(getattr(question, "tenant_id", 1) or 1),
            request_id=int(request.id),
            user_id=int(user_id),
            role_in_request=ROLE_ANSWERER,
            decision=DECISION_PENDING,
            decided_at=None,
        )
        await self.approver_repo.create_many([row])
        refreshed = await self.request_repo.get_by_id(int(request.id))
        if refreshed is None or str(refreshed.status) != PUBLISH_PENDING:
            created = await self.approver_repo.get_for_user(int(request.id), int(user_id))
            if created is not None and str(created.decision) == DECISION_PENDING:
                await self.approver_repo.delete(int(created.id))
            return
        refreshed = await self._try_extend_for_late_answerer(refreshed)
        from bisheng.qa_expert.domain.publish_approval_bridge import add_pending_task, refresh_expire_snapshot

        await add_pending_task(refreshed, question, int(user_id))
        await refresh_expire_snapshot(refreshed)
        await self._notify(
            "publish_approver_added",
            question,
            extra={"request_id": request.id, "added_user_id": int(user_id)},
        )

    async def _sync_approval_center(self, request) -> None:
        """把 qa_publish_* 状态同步到审批中心待办。"""
        if request is None:
            return
        from bisheng.qa_expert.domain.publish_approval_bridge import sync_from_publish_request

        await sync_from_publish_request(request)

    async def _approve_question(self, request: PublishRequest, question) -> None:
        """全体同意后不可逆公开；定向首次采纳未写 eligibility 时在此补快照。"""
        await self.request_repo.update(int(request.id), status=PUBLISH_APPROVED)
        await self.question_repo.update(
            int(question.id),
            question_type=QUESTION_TYPE_PUBLIC,
            active_publish_request_id=None,
        )
        question.question_type = QUESTION_TYPE_PUBLIC
        question.active_publish_request_id = None
        await self._write_eligibility_if_missing(question)

    async def _write_eligibility_if_missing(self, question) -> None:
        existing = await self.eligibility_repo.list_user_ids(int(question.id))
        if existing:
            return
        invite_map = await self.invite_repo.list_user_ids_by_question_ids([int(question.id)])
        invited = set(invite_map.get(int(question.id), set()))
        answers = await self.answer_repo.list_all_by_question_id(int(question.id))
        tenant_id = int(getattr(question, "tenant_id", 1) or 1)
        rows: list[AnswerEligibility] = []
        seen: set[int] = set()
        for uid in invited:
            uid = int(uid)
            if uid in seen:
                continue
            seen.add(uid)
            rows.append(
                AnswerEligibility(
                    tenant_id=tenant_id,
                    question_id=int(question.id),
                    user_id=uid,
                    source=ELIGIBILITY_INVITED,
                )
            )
        for answer in answers:
            uid = getattr(answer, "user_id", None)
            if uid is None:
                continue
            uid = int(uid)
            if uid in seen:
                continue
            seen.add(uid)
            rows.append(
                AnswerEligibility(
                    tenant_id=tenant_id,
                    question_id=int(question.id),
                    user_id=uid,
                    source=ELIGIBILITY_ANSWER,
                )
            )
        await self.eligibility_repo.create_many(rows)

    async def _close_request(self, request: PublishRequest, status: str, question) -> None:
        await self.request_repo.update(int(request.id), status=status)
        if int(getattr(question, "active_publish_request_id", 0) or 0) == int(request.id):
            await self.question_repo.update(int(question.id), active_publish_request_id=None)

    async def _notify(self, event: str, question, extra: dict[str, Any] | None = None) -> None:
        hook = self.notify
        if callable(hook):
            await hook(event, question, extra or {})
            return
        try:
            await self._send_inbox(event, question, extra or {})
        except Exception:
            logger.exception("qa.publish.notify_failed event={}", event)

    async def _send_inbox(self, event: str, question, extra: dict[str, Any]) -> None:
        """转公开站内信：相关人通知；待办入口靠 approval_instance_id。

        终态（通过/拒绝/过期/结束）若无操作人，用系统发件，保证提问者也能收到。
        """
        from bisheng.approval.domain.repositories.approval_instance_repository import (
            ApprovalInstanceRepository,
        )
        from bisheng.qa_expert.domain.inbox_notice import display_name_for_trigger, send_qa_inbox
        from bisheng.qa_expert.domain.publish_approval_bridge import business_key_for

        todo_events = {"publish_started", "publish_approver_added"}
        result_events = {
            "publish_approved",
            "publish_rejected",
            "publish_expired",
            "publish_ended",
            "publish_default_approved",
        }
        sender = extra.get("user")
        sender_id = int(getattr(sender, "user_id", 0) or 0) if sender is not None else 0
        # 终态是系统结果，没有操作人。若把提问者填成发件人，send_qa_inbox 会把他从收件人剔除。
        use_system_sender = event in result_events and sender_id <= 0
        if sender_id <= 0 and not use_system_sender:
            sender_id = int(question.user_id)
        if use_system_sender:
            display, masked = "系统", True
            sender_id = 0
        else:
            real_name = extra.get("sender_name") or getattr(sender, "user_name", "") or ""
            asker_anonymous = bool(int(getattr(question, "asker_anonymous", 0) or 0))
            anonymous = bool(asker_anonymous) if sender_id == int(question.user_id) else bool(extra.get("anonymous"))
            display, masked = await display_name_for_trigger(
                question,
                user_id=sender_id,
                real_name=real_name,
                anonymous=anonymous,
                reveal_on_public=getattr(question, "asker_reveal_on_public", None)
                if sender_id == int(question.user_id)
                else extra.get("reveal_on_public"),
            )
        receivers: list[int] = []
        request_id = extra.get("request_id")
        if request_id:
            for row in await self.approver_repo.list_by_request(int(request_id)):
                receivers.append(int(row.user_id))
        receivers.append(int(question.user_id))
        added = extra.get("added_user_id")
        if added:
            receivers.append(int(added))
        instance_id = None
        if request_id:
            inst = await ApprovalInstanceRepository.find_latest_by_business_key(
                tenant_id=int(getattr(question, "tenant_id", 1) or 1),
                scenario_code="qa_question_publish",
                business_key=business_key_for(int(request_id)),
            )
            if inst is not None:
                instance_id = int(inst.id)
        business_type = "approval_instance_id" if event in todo_events and instance_id else "qa_question"
        await send_qa_inbox(
            action_code=f"qa_{event}",
            system_text=f"qa_expert_{event}",
            question=question,
            receivers=receivers,
            sender_user_id=sender_id,
            sender_display=display or "系统",
            sender_anonymous=masked,
            request_id=int(request_id) if request_id else None,
            instance_id=instance_id,
            business_type=business_type if event in todo_events or event in result_events else "qa_question",
        )
