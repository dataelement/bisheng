# ruff: noqa: RUF002, RUF003
"""专家问答资格引擎：展示态与写操作 capabilities 的唯一入口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bisheng.database.models.qa_expert import (
    EXPERT_STATUS_ACTIVE,
    QUESTION_TYPE_DIRECTED,
    QUESTION_TYPE_PUBLIC,
)

DISPLAY_UNANSWERED = "unanswered"
DISPLAY_PENDING_ADOPT = "pending_adopt"
DISPLAY_SOLVED = "solved"
UNRESOLVED_DISPLAY_STATUSES = frozenset({DISPLAY_UNANSWERED, DISPLAY_PENDING_ADOPT})

# 对齐 Portal isPortalAdmin：角色名 + admin 账号；同时承认 UserPayload.is_admin()
_EXPERT_LIBRARY_ADMIN_ROLES = frozenset({"管理员", "系统管理员", "admin"})
_EXPERT_LIBRARY_ADMIN_ACCOUNTS = frozenset({"admin"})


@dataclass(frozen=True)
class QuestionCapabilities:
    """详情/写路径共用的可操作项；visible=False 时其余应为 False。"""

    can_edit: bool
    can_delete_question: bool
    can_answer: bool
    can_adopt: bool
    can_comment: bool
    can_start_publish: bool
    can_decide_publish: bool
    can_view_real_identity: bool
    visible: bool = True


@dataclass(frozen=True)
class CapabilityResult:
    """资格引擎输出：派生三态 + capabilities。"""

    display_status: str
    capabilities: QuestionCapabilities


@dataclass(frozen=True)
class CapabilitySnapshot:
    """解析资格所需的仓储快照；单测可直接构造，不查库。"""

    expert: Any | None = None
    invited_user_ids: frozenset[int] = field(default_factory=frozenset)
    eligibility_user_ids: frozenset[int] = field(default_factory=frozenset)
    effective_answer_count: int = 0
    user_has_effective_answer: bool = False
    has_pending_publish: bool = False
    latest_publish_status: str | None = None
    # 仅仍 pending 的审批人；发起人默认同意后不在此集合，can_decide_publish 为 False。
    approver_user_ids: frozenset[int] = field(default_factory=frozenset)
    viewer_publish_decision: str | None = None


def derive_display_status(*, effective_answer_count: int, adopt_count: int) -> str:
    """由有效回答数与采纳数派生三态；不引入「已关闭」。"""
    if adopt_count > 0:
        return DISPLAY_SOLVED
    if effective_answer_count > 0:
        return DISPLAY_PENDING_ADOPT
    return DISPLAY_UNANSWERED


def is_unresolved(display_status: str) -> bool:
    """「未解决」筛选 = 未回答 ∪ 待采纳。"""
    return display_status in UNRESOLVED_DISPLAY_STATUSES


def _normalize_identity(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def is_expert_library_admin(user: Any | None) -> bool:
    """专家库管理员：is_admin() 或 Portal 角色名/admin 账号；不查 role_access。"""
    if user is None:
        return False
    is_admin = getattr(user, "is_admin", None)
    if callable(is_admin) and bool(is_admin()):
        return True
    account = _normalize_identity(getattr(user, "user_name", None) or getattr(user, "account", None))
    if account in _EXPERT_LIBRARY_ADMIN_ACCOUNTS:
        return True
    role = getattr(user, "role", None)
    role_names = getattr(user, "role_names", None)
    candidates: list[Any] = []
    if role:
        candidates.append(role)
    if isinstance(role_names, (list, tuple, set, frozenset)):
        candidates.extend(role_names)
    for name in candidates:
        if _normalize_identity(name) in {item.lower() for item in _EXPERT_LIBRARY_ADMIN_ROLES}:
            return True
        # 中文角色名大小写不变，再按原字面匹配
        if str(name).strip() in _EXPERT_LIBRARY_ADMIN_ROLES:
            return True
    return False


def _user_id(user: Any | None) -> int | None:
    if user is None:
        return None
    value = getattr(user, "user_id", None)
    return int(value) if value is not None else None


def _expert_active(snapshot: CapabilitySnapshot) -> bool:
    expert = snapshot.expert
    if expert is None:
        return False
    status = getattr(expert, "status", EXPERT_STATUS_ACTIVE)
    return int(status) == EXPERT_STATUS_ACTIVE


class CapabilityResolver:
    """单入口资格引擎；写接口与详情必须复用，避免列表/详情/写路径不一致。"""

    def resolve(self, user: Any | None, question: Any, snapshot: CapabilitySnapshot) -> CapabilityResult:
        """根据用户、问题与仓储快照计算 display_status 与 capabilities。"""
        display_status = derive_display_status(
            effective_answer_count=snapshot.effective_answer_count,
            adopt_count=int(getattr(question, "adopt_count", 0) or 0),
        )
        admin = is_expert_library_admin(user)
        uid = _user_id(user)
        asker_id = int(question.user_id)
        is_asker = uid is not None and uid == asker_id
        question_type = str(getattr(question, "question_type", QUESTION_TYPE_PUBLIC) or QUESTION_TYPE_PUBLIC)
        locked = bool(getattr(question, "content_locked", 0))
        visible = self._is_visible(
            user=user,
            question_type=question_type,
            is_asker=is_asker,
            uid=uid,
            snapshot=snapshot,
            admin=admin,
        )
        if not visible:
            return CapabilityResult(
                display_status=display_status,
                capabilities=self._denied(can_view_real_identity=admin),
            )

        can_mutate_question = is_asker and not locked
        can_answer = self._can_answer(
            uid=uid,
            is_asker=is_asker,
            question_type=question_type,
            snapshot=snapshot,
            adopt_count=int(getattr(question, "adopt_count", 0) or 0),
        )
        can_comment = self._can_comment(
            uid=uid,
            is_asker=is_asker,
            question_type=question_type,
            snapshot=snapshot,
        )
        can_start_publish = (
            question_type == QUESTION_TYPE_DIRECTED
            and display_status == DISPLAY_SOLVED
            and not snapshot.has_pending_publish
            and snapshot.latest_publish_status != "ended"
            and (is_asker or snapshot.user_has_effective_answer)
        )
        # 只给尚未决策的审批人；发起人创建时已写入 approved，不能再点同意/拒绝。
        can_decide_publish = snapshot.has_pending_publish and uid is not None and uid in snapshot.approver_user_ids
        return CapabilityResult(
            display_status=display_status,
            capabilities=QuestionCapabilities(
                can_edit=can_mutate_question,
                can_delete_question=can_mutate_question,
                can_answer=can_answer,
                can_adopt=is_asker and int(getattr(question, "adopt_count", 0) or 0) < 3,
                can_comment=can_comment,
                can_start_publish=can_start_publish,
                can_decide_publish=can_decide_publish,
                can_view_real_identity=admin,
                visible=True,
            ),
        )

    @staticmethod
    def _denied(*, can_view_real_identity: bool) -> QuestionCapabilities:
        return QuestionCapabilities(
            can_edit=False,
            can_delete_question=False,
            can_answer=False,
            can_adopt=False,
            can_comment=False,
            can_start_publish=False,
            can_decide_publish=False,
            can_view_real_identity=can_view_real_identity,
            visible=False,
        )

    @staticmethod
    def _is_visible(
        *,
        user: Any | None,
        question_type: str,
        is_asker: bool,
        uid: int | None,
        snapshot: CapabilitySnapshot,
        admin: bool,
    ) -> bool:
        if user is None or uid is None:
            return False
        if question_type != QUESTION_TYPE_DIRECTED:
            return True
        return is_asker or admin or uid in snapshot.invited_user_ids

    @staticmethod
    def _can_answer(
        *,
        uid: int | None,
        is_asker: bool,
        question_type: str,
        snapshot: CapabilitySnapshot,
        adopt_count: int,
    ) -> bool:
        if uid is None or is_asker or not _expert_active(snapshot):
            return False
        if question_type == QUESTION_TYPE_DIRECTED:
            return uid in snapshot.invited_user_ids
        if adopt_count <= 0:
            return True
        return uid in snapshot.eligibility_user_ids

    @staticmethod
    def _can_comment(
        *,
        uid: int | None,
        is_asker: bool,
        question_type: str,
        snapshot: CapabilitySnapshot,
    ) -> bool:
        if uid is None:
            return False
        if question_type != QUESTION_TYPE_DIRECTED:
            return True
        return is_asker or snapshot.user_has_effective_answer
