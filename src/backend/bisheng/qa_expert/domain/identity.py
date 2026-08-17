# ruff: noqa: RUF002
"""题内匿名别名与身份脱敏：序号按首次出现时间递增，删内容不回收。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bisheng.database.models.qa_expert import QUESTION_TYPE_DIRECTED, QUESTION_TYPE_PUBLIC, AnonymousAlias
from bisheng.qa_expert.domain.capability import is_expert_library_admin
from bisheng.qa_expert.domain.repositories import AnonymousAliasRepository

ALIAS_PREFIX = "匿名同事"


def alias_label_for_ord(alias_ord: int) -> str:
    """序号 1→A、2→B；超过 26 用 AA、AB…，永不复用已分配序号。"""
    if alias_ord <= 0:
        alias_ord = 1
    n = alias_ord
    letters: list[str] = []
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return f"{ALIAS_PREFIX}{''.join(reversed(letters))}"


@dataclass
class IdentityView:
    """服务端已脱敏的身份；真名字段仅管理员可读。"""

    display_name: str
    avatar_url: str | None
    anonymous: bool
    real_user_id: int | None = None
    real_name: str | None = None
    department: str | None = None
    title: str | None = None

    def to_dict(self, *, can_view_real_identity: bool) -> dict[str, Any]:
        """非管理员不下发真名/真 user_id。"""
        payload: dict[str, Any] = {
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "anonymous": self.anonymous,
        }
        if can_view_real_identity:
            payload["real_user_id"] = self.real_user_id
            payload["real_name"] = self.real_name
            payload["department"] = self.department
            payload["title"] = self.title
        return payload


def should_reveal_name(
    *,
    anonymous: bool,
    question_type: str,
    reveal_on_public: bool | int | None,
) -> bool:
    """转公开后按预存 reveal_on_public 展示，不再询问。"""
    if not anonymous:
        return True
    if str(question_type or "") != QUESTION_TYPE_PUBLIC:
        return False
    return bool(int(reveal_on_public or 0))


def persist_anonymous_choice(
    *,
    anonymous: bool,
    reveal_on_public: bool | int | None,
    question_type: str,
) -> tuple[int, int | None]:
    """把客户端匿名选项落成表字段；未匿名不存 reveal。定向匿名必须先选转公开姓名。"""
    if not anonymous:
        return 0, None
    if str(question_type or "") == QUESTION_TYPE_DIRECTED and reveal_on_public is None:
        from bisheng.common.errcode.qa_expert import QaExpertAnonymousRevealRequiredError

        raise QaExpertAnonymousRevealRequiredError()
    if reveal_on_public is None:
        return 1, None
    return 1, 1 if int(reveal_on_public) else 0


def copy_stored_anonymous_flags(
    anonymous: bool | int | None,
    reveal_on_public: bool | int | None,
) -> tuple[int, int | None]:
    """继承已落库的匿名/转公开姓名，不读客户端覆盖。"""
    if not int(anonymous or 0):
        return 0, None
    if reveal_on_public is None:
        return 1, None
    return 1, 1 if int(reveal_on_public) else 0


class IdentityService:
    """读写 qa_anonymous_alias，并把展示身份做成 IdentityView。"""

    def __init__(self, alias_repo: AnonymousAliasRepository | None = None):
        self.alias_repo = alias_repo or AnonymousAliasRepository()
        # 列表一次预加载后复用；(question_id, user_id) → 别名。None 表示未预加载。
        self._alias_cache: dict[tuple[int, int], AnonymousAlias] | None = None

    async def preload_for_questions(self, question_ids: list[int]) -> None:
        """把本页别名一次载入缓存，后续 mask_identity 不再按人打库。"""
        rows = await self.alias_repo.list_by_question_ids(question_ids)
        self._alias_cache = {
            (int(row.question_id), int(row.user_id)): row
            for row in rows
            if getattr(row, "question_id", None) is not None and getattr(row, "user_id", None) is not None
        }

    async def get_or_assign_alias(
        self,
        *,
        question_id: int,
        user_id: int,
        tenant_id: int = 1,
    ) -> AnonymousAlias:
        """同题同用户返回已有别名；否则按 max(alias_ord)+1 分配，不回收已删内容序号。"""
        cache_key = (int(question_id), int(user_id))
        if self._alias_cache is not None:
            cached = self._alias_cache.get(cache_key)
            if cached is not None:
                return cached
        else:
            existing = await self.alias_repo.get_by_question_user(question_id, user_id)
            if existing is not None:
                return existing
        next_ord = await self.alias_repo.next_alias_ord(question_id)
        row = AnonymousAlias(
            tenant_id=tenant_id,
            question_id=question_id,
            user_id=user_id,
            alias_ord=next_ord,
            alias_label=alias_label_for_ord(next_ord),
        )
        created = await self.alias_repo.create(row)
        if self._alias_cache is not None:
            self._alias_cache[cache_key] = created
        return created

    async def mask_identity(
        self,
        viewer: Any,
        *,
        question_id: int,
        user_id: int,
        real_name: str,
        anonymous: bool,
        question_type: str,
        reveal_on_public: bool | int | None = None,
        tenant_id: int = 1,
        department: str | None = None,
        title: str | None = None,
        avatar_url: str | None = None,
    ) -> IdentityView:
        """按匿名预选项与问题当前类型生成展示身份；管理员可读真名。"""
        can_view_real = is_expert_library_admin(viewer)
        revealed = should_reveal_name(
            anonymous=anonymous,
            question_type=question_type,
            reveal_on_public=reveal_on_public,
        )
        display_name = real_name
        shown_anonymous = False
        if anonymous and not revealed:
            alias = await self.get_or_assign_alias(
                question_id=question_id,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            display_name = alias.alias_label
            shown_anonymous = True
        view = IdentityView(
            display_name=display_name,
            avatar_url=None if shown_anonymous else avatar_url,
            anonymous=shown_anonymous,
            real_user_id=user_id,
            real_name=real_name,
            department=department,
            title=title,
        )
        if not can_view_real:
            view.real_user_id = None
            view.real_name = None
            view.department = None
            view.title = None
        return view
