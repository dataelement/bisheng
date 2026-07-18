"""F028 T013 — unit tests for KnowledgeSpaceService.list_uploadable_spaces.

The method drives the ``AddToKnowledgeModal`` data source in the workstation
conversation-export flow. We verify three things:

- Admin path (PermissionService.list_accessible_ids returns None) lists every
  SPACE-type knowledge in tenant scope.
- Normal user path unions OpenFGA-accessible ids with creator-owned ids,
  ordered by update_time desc.
- Keyword filter does substring (case-insensitive) match against name.

AC coverage: AC-17
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from bisheng.knowledge.domain.models.knowledge import (
    Knowledge,
    KnowledgeDao,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.user.domain.services.auth import LoginUser

# --- Fixtures --------------------------------------------------------------


def _make_knowledge(
    id_: int,
    name: str,
    *,
    user_id: int = 1,
    type_: int = KnowledgeTypeEnum.SPACE.value,
    description: str | None = None,
    update_time: datetime | None = None,
) -> Knowledge:
    return Knowledge(
        id=id_,
        name=name,
        type=type_,
        user_id=user_id,
        description=description,
        update_time=update_time or datetime(2026, 5, 31, 0, 0, 0),
        tenant_id=1,
    )


@pytest.fixture
def service() -> KnowledgeSpaceService:
    """Construct KnowledgeSpaceService with a stub request + login_user.

    We only exercise the new list method which depends solely on
    self.login_user; the request and helper services stay unused.
    """
    request = MagicMock()
    login_user = LoginUser(
        user_id=1,
        user_name="Admin",
        user_role=[],
        tenant_id=1,
    )
    return KnowledgeSpaceService(request=request, login_user=login_user)


@pytest.fixture
def patch_perm_and_dao(monkeypatch: pytest.MonkeyPatch):
    """Mock PermissionService.list_accessible_ids and KnowledgeDao methods."""

    state: dict = {
        "accessible_ids": [],  # None → admin path; list → normal user path
        "created_ids": [],  # creator-owned space ids
        "spaces_by_ids": {},  # id → Knowledge
        "uploadable_ids": None,  # None → every candidate has upload_file;
        # set → only these ids do (others filtered)
    }

    async def _fake_list_accessible_ids(cls, *, user_id, relation, object_type, login_user=None):
        return state["accessible_ids"]

    async def _fake_effective_perms(self, object_type, object_id, *, space_id=None):
        # ⑥: list_uploadable_spaces now filters candidates by the fine-grained
        # upload_file permission. Default: grant it to all (filter is a no-op so
        # the union/type/keyword/sort assertions below still hold); per-id
        # control via set_uploadable_ids() exercises the actual filtering.
        if state["uploadable_ids"] is None or int(object_id) in state["uploadable_ids"]:
            return {"upload_file", "view_space"}
        return {"view_space"}

    async def _fake_get_created_ids(cls, user_id, knowledge_type):
        return list(state["created_ids"])

    async def _fake_get_list_by_ids(cls, ids):
        return [state["spaces_by_ids"][i] for i in ids if i in state["spaces_by_ids"]]

    monkeypatch.setattr(
        PermissionService,
        "list_accessible_ids",
        classmethod(_fake_list_accessible_ids),
    )
    monkeypatch.setattr(
        KnowledgeDao,
        "aget_knowledge_ids_created_by",
        classmethod(_fake_get_created_ids),
    )
    monkeypatch.setattr(
        KnowledgeDao,
        "aget_list_by_ids",
        classmethod(_fake_get_list_by_ids),
    )
    monkeypatch.setattr(
        KnowledgeSpaceService,
        "_get_effective_permission_ids",
        _fake_effective_perms,
    )

    class _Registry:
        @staticmethod
        def set_accessible_ids(ids):
            state["accessible_ids"] = ids

        @staticmethod
        def set_created_ids(ids):
            state["created_ids"] = list(ids)

        @staticmethod
        def set_spaces(spaces):
            state["spaces_by_ids"] = {s.id: s for s in spaces}

        @staticmethod
        def set_uploadable_ids(ids):
            state["uploadable_ids"] = set(ids)

    return _Registry()


# --- Normal user path ------------------------------------------------------


async def test_list_uploadable_filters_by_can_edit(service, patch_perm_and_dao):
    """AC-17: 普通用户取 OpenFGA can_edit 列表, 拉对应 Knowledge 元信息。"""
    patch_perm_and_dao.set_accessible_ids(["42", "56"])
    patch_perm_and_dao.set_created_ids([])
    patch_perm_and_dao.set_spaces(
        [
            _make_knowledge(42, "宏观研究"),
            _make_knowledge(56, "黄金专题"),
        ]
    )

    result = await service.list_uploadable_spaces()
    ids = sorted(s.id for s in result)
    assert ids == [42, 56]


async def test_list_uploadable_unions_creator_owned(service, patch_perm_and_dao):
    """FGA list + creator-owned spaces 取并集。"""
    patch_perm_and_dao.set_accessible_ids(["42"])
    patch_perm_and_dao.set_created_ids([99])
    patch_perm_and_dao.set_spaces(
        [
            _make_knowledge(42, "宏观研究"),
            _make_knowledge(99, "我自己创建的"),
        ]
    )

    result = await service.list_uploadable_spaces()
    ids = sorted(s.id for s in result)
    assert ids == [42, 99]


async def test_list_uploadable_sorts_by_update_time_desc(service, patch_perm_and_dao):
    """按 update_time desc 排序。"""
    now = datetime(2026, 5, 31, 0, 0, 0)
    patch_perm_and_dao.set_accessible_ids(["1", "2", "3"])
    patch_perm_and_dao.set_spaces(
        [
            _make_knowledge(1, "oldest", update_time=now - timedelta(days=10)),
            _make_knowledge(2, "newest", update_time=now),
            _make_knowledge(3, "middle", update_time=now - timedelta(days=5)),
        ]
    )

    result = await service.list_uploadable_spaces()
    assert [s.id for s in result] == [2, 3, 1]


async def test_list_uploadable_excludes_non_space_type(service, patch_perm_and_dao):
    """KnowledgeDao 返了非 SPACE 类型的资源 → 必须过滤掉。"""
    patch_perm_and_dao.set_accessible_ids(["1", "2"])
    patch_perm_and_dao.set_spaces(
        [
            _make_knowledge(1, "space", type_=KnowledgeTypeEnum.SPACE.value),
            _make_knowledge(2, "normal-kb", type_=KnowledgeTypeEnum.NORMAL.value),
        ]
    )

    result = await service.list_uploadable_spaces()
    assert [s.id for s in result] == [1]


async def test_list_uploadable_excludes_no_upload_permission(service, patch_perm_and_dao):
    """⑥: a candidate the user can READ but has NO upload_file on is excluded.
    can_read surfaces it as a candidate; the fine-grained filter drops it — the
    custom-template-grants-upload-under-viewer case the coarse relation missed."""
    patch_perm_and_dao.set_accessible_ids(["1", "2"])
    patch_perm_and_dao.set_spaces(
        [
            _make_knowledge(1, "can-upload"),
            _make_knowledge(2, "read-only"),
        ]
    )
    patch_perm_and_dao.set_uploadable_ids([1])  # only space 1 grants upload_file

    result = await service.list_uploadable_spaces()
    assert [s.id for s in result] == [1]


# --- Empty paths ------------------------------------------------------------


async def test_list_uploadable_empty(service, patch_perm_and_dao):
    """AC-17: 用户无可上传空间 → 返 []。"""
    patch_perm_and_dao.set_accessible_ids([])
    patch_perm_and_dao.set_created_ids([])
    patch_perm_and_dao.set_spaces([])

    result = await service.list_uploadable_spaces()
    assert result == []


async def test_list_uploadable_non_numeric_ids_skipped(service, patch_perm_and_dao):
    """FGA 返回的 id 非数字 → 跳过, 不抛 (防御性)。"""
    patch_perm_and_dao.set_accessible_ids(["not-a-number", "42"])
    patch_perm_and_dao.set_created_ids([])
    patch_perm_and_dao.set_spaces([_make_knowledge(42, "宏观研究")])

    result = await service.list_uploadable_spaces()
    assert [s.id for s in result] == [42]


# --- Keyword filter --------------------------------------------------------


async def test_list_uploadable_keyword_filter(service, patch_perm_and_dao):
    """AC-17: 关键词子串匹配 (大小写不敏感)。"""
    patch_perm_and_dao.set_accessible_ids(["1", "2", "3"])
    patch_perm_and_dao.set_spaces(
        [
            _make_knowledge(1, "黄金行情"),
            _make_knowledge(2, "宏观研究"),
            _make_knowledge(3, "股票黄金 ETF"),
        ]
    )

    result = await service.list_uploadable_spaces(keyword="黄金")
    ids = sorted(s.id for s in result)
    assert ids == [1, 3]


async def test_list_uploadable_keyword_case_insensitive(service, patch_perm_and_dao):
    """关键词大小写不敏感对英文 name 也生效。"""
    patch_perm_and_dao.set_accessible_ids(["1"])
    patch_perm_and_dao.set_spaces([_make_knowledge(1, "Macro Research")])

    result = await service.list_uploadable_spaces(keyword="MACRO")
    assert [s.id for s in result] == [1]


# --- Admin path ------------------------------------------------------------


async def test_list_uploadable_admin_sees_all_spaces(service, patch_perm_and_dao, monkeypatch):
    """list_accessible_ids 返 None (admin) → 直查数据库列出所有 SPACE 类型 knowledge."""
    patch_perm_and_dao.set_accessible_ids(None)

    # The admin branch falls through to a raw select() with session.exec().
    # Stub the session context manager + exec to return a curated list.
    admin_spaces = [
        _make_knowledge(7, "tenant-wide-1"),
        _make_knowledge(8, "tenant-wide-2"),
    ]

    class _StubResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _StubSession:
        async def exec(self, _stmt):
            return _StubResult(admin_spaces)

    class _CMSession:
        async def __aenter__(self):
            return _StubSession()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        lambda: _CMSession(),
    )

    result = await service.list_uploadable_spaces()
    ids = sorted(s.id for s in result)
    assert ids == [7, 8]
