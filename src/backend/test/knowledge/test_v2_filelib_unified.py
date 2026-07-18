"""F030 — v2 filelib unified API facade tests.

Scope: verify the *facade dispatch* logic added in F030 (T06/T07/T08) and the
identity resolution (T02) / error code (T01) without requiring real
DB/Milvus/ES/OpenFGA infrastructure. The endpoint coroutines are invoked
directly with the service layer monkeypatched, so these run in plain pytest.

Heavier end-to-end coverage (real retrieval against Milvus/ES, OpenFGA
permission filtering, cursor round-trips over a live DB) is **测试降级 → manual /
infra-backed e2e** and tracked in tasks.md §实际偏差记录.
"""
import pytest
from fastapi import HTTPException

import bisheng.open_endpoints.api.endpoints.filelib as filelib
from bisheng.common.errcode.knowledge import KnowledgeTypeNotSupportedError
from bisheng.knowledge.domain.models.knowledge import (AuthTypeEnum, KnowledgeCreate,
                                                       KnowledgeTypeEnum, KnowledgeUpdate)
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


class _FakeUser:
    user_id = 1
    user_name = "operator"
    tenant_id = 1


class _Row:
    """Stand-in for a Knowledge ORM row (only ``type`` / ``is_released`` used)."""

    def __init__(self, ktype: int, is_released: bool = False):
        self.type = ktype
        self.is_released = is_released


@pytest.fixture(autouse=True)
def _patch_identity(monkeypatch):
    """Default operator + resolve_operator return a fake user (no DB)."""
    async def _fake_default():
        return _FakeUser()

    async def _fake_resolve(user_id=None):
        return _FakeUser()

    monkeypatch.setattr(filelib, "get_default_operator_async", _fake_default)
    monkeypatch.setattr(filelib, "resolve_operator", _fake_resolve)


# --------------------------------------------------------------------------- #
# T01 — error code
# --------------------------------------------------------------------------- #
def test_errcode_value():
    """AC-04/AC-05: the new error code is registered at 10962 (109 module)."""
    assert KnowledgeTypeNotSupportedError.Code == 10962


# --------------------------------------------------------------------------- #
# T06 — create dispatch
# --------------------------------------------------------------------------- #
async def test_create_dispatch_kb(monkeypatch):
    """AC-07/AC-12: type=0 → KnowledgeService; auth_type/is_released forced to default;
    output enriched to KnowledgeRead (user_name + permission_ids)."""
    captured = {}

    async def _fake_acreate(cls, request, login_user, knowledge):
        captured["knowledge"] = knowledge
        return type("K", (), {"id": 1, "type": knowledge.type, "user_id": 1})()

    async def _fake_convert(cls, login_user, knowledge_list):
        return [{"id": 1, "type": knowledge_list[0].type,
                 "user_name": "operator", "permission_ids": ["use_kb", "edit_kb"]}]

    monkeypatch.setattr(KnowledgeService, "acreate_knowledge", classmethod(_fake_acreate))
    monkeypatch.setattr(KnowledgeService, "aconvert_knowledge_read", classmethod(_fake_convert))

    req = KnowledgeCreate(name="kb", type=KnowledgeTypeEnum.NORMAL.value, model="12",
                          auth_type=AuthTypeEnum.APPROVAL, is_released=True)
    resp = await filelib.create(request=None, knowledge=req, version_repo=None, doc_repo=None)
    assert resp.data["type"] == KnowledgeTypeEnum.NORMAL.value
    assert resp.data["user_name"] == "operator"            # enriched
    assert resp.data["permission_ids"]                     # enriched, non-empty
    # AC-12: KB ignores auth_type / is_released (forced to defaults before create).
    assert captured["knowledge"].auth_type == AuthTypeEnum.PUBLIC
    assert captured["knowledge"].is_released is False


async def test_create_dispatch_space(monkeypatch):
    """AC-09: type=3 → create_knowledge_space (model ignored); output enriched with
    user_name + creator's effective space permission_ids."""
    captured = {}

    async def _fake_space_create(self, **kwargs):
        captured.update(kwargs)
        return type("S", (), {
            "id": 7,
            "model_dump": lambda self: {"id": 7, "name": "space", "type": KnowledgeTypeEnum.SPACE.value},
        })()

    async def _fake_eff(self, object_type, object_id, **kw):
        return {"view_space", "edit_space"}

    monkeypatch.setattr(KnowledgeSpaceService, "create_knowledge_space", _fake_space_create)
    monkeypatch.setattr(KnowledgeSpaceService, "_get_effective_permission_ids", _fake_eff)

    req = KnowledgeCreate(name="space", type=KnowledgeTypeEnum.SPACE.value, model="ignored",
                          auth_type=AuthTypeEnum.PRIVATE, is_released=True)
    resp = await filelib.create(request=None, knowledge=req, version_repo=None, doc_repo=None)
    assert resp.data.type == KnowledgeTypeEnum.SPACE.value
    assert resp.data.user_name == "operator"               # enriched
    assert set(resp.data.permission_ids) == {"edit_space", "view_space"}  # enriched
    # model is never forwarded to the space create path.
    assert "model" not in captured
    assert captured["auth_type"] == AuthTypeEnum.PRIVATE


@pytest.mark.parametrize("bad_type", [KnowledgeTypeEnum.PRIVATE.value, 9])
async def test_create_rejects_unsupported_type(bad_type):
    """AC-04/AC-05: type=2 (personal KB) and illegal types are rejected."""
    req = KnowledgeCreate(name="x", type=bad_type, model="12")
    with pytest.raises(HTTPException):
        await filelib.create(request=None, knowledge=req, version_repo=None, doc_repo=None)


# --------------------------------------------------------------------------- #
# T06 — update dispatch
# --------------------------------------------------------------------------- #
async def test_update_dispatch_space_preserves_is_released(monkeypatch):
    """AC-14: space update routes to update_knowledge_space, preserving is_released."""
    captured = {}

    async def _fake_query(knowledge_id):
        return _Row(KnowledgeTypeEnum.SPACE.value, is_released=True)

    async def _fake_space_update(self, **kwargs):
        captured.update(kwargs)
        return {"id": kwargs["space_id"]}

    monkeypatch.setattr(filelib.KnowledgeDao, "aquery_by_id", staticmethod(_fake_query))
    monkeypatch.setattr(KnowledgeSpaceService, "update_knowledge_space", _fake_space_update)

    req = KnowledgeUpdate(knowledge_id=7, name="new", description=None)
    await filelib.update_knowledge(request=None, knowledge=req, version_repo=None, doc_repo=None)
    assert captured["is_released"] is True          # preserved, not clobbered
    assert captured["description"] == ""            # missing description → empty (AD-09)


async def test_update_missing_resource(monkeypatch):
    """AC-16: unknown knowledge_id → NotFoundError (HTTPException)."""
    async def _fake_query(knowledge_id):
        return None

    monkeypatch.setattr(filelib.KnowledgeDao, "aquery_by_id", staticmethod(_fake_query))
    req = KnowledgeUpdate(knowledge_id=999, name="x")
    with pytest.raises(HTTPException):
        await filelib.update_knowledge(request=None, knowledge=req, version_repo=None, doc_repo=None)


# --------------------------------------------------------------------------- #
# T06 — list dispatch
# --------------------------------------------------------------------------- #
async def test_list_dispatch_kb(monkeypatch):
    """AC-01: type=0 → KnowledgeService.get_knowledge (cursor page)."""
    async def _fake_get(cls, request, login_user, ktype, **kwargs):
        return {"data": [], "page_size": 10, "has_more": False, "next_cursor": None}

    monkeypatch.setattr(KnowledgeService, "get_knowledge", classmethod(_fake_get))
    resp = await filelib.get_knowledge(
        request=None, knowledge_type=KnowledgeTypeEnum.NORMAL.value, name=None,
        sort_by="update_time", page_size=10, cursor=None, user_id=None,
        version_repo=None, doc_repo=None,
    )
    assert resp.data["has_more"] is False
    assert "total" not in resp.data  # INV-6: no total


async def test_list_dispatch_space(monkeypatch):
    """AC-02: type=3 → KnowledgeSpaceService.alist_mine_and_joined_cursor."""
    async def _fake_list(self, **kwargs):
        return {"data": [], "page_size": 10, "has_more": False, "next_cursor": None}

    monkeypatch.setattr(KnowledgeSpaceService, "alist_mine_and_joined_cursor", _fake_list)
    resp = await filelib.get_knowledge(
        request=None, knowledge_type=KnowledgeTypeEnum.SPACE.value, name=None,
        sort_by="update_time", page_size=10, cursor=None, user_id=None,
        version_repo=None, doc_repo=None,
    )
    assert resp.data["has_more"] is False


async def test_list_rejects_type2():
    """AC-04: type=2 not listable via v2."""
    with pytest.raises(HTTPException):
        await filelib.get_knowledge(
            request=None, knowledge_type=KnowledgeTypeEnum.PRIVATE.value, name=None,
            sort_by="update_time", page_size=10, cursor=None, user_id=None,
            version_repo=None, doc_repo=None,
        )


# --------------------------------------------------------------------------- #
# T08 — file list dispatch
# --------------------------------------------------------------------------- #
async def test_filelist_dispatch_kb(monkeypatch):
    """AC-26: KB file list → aget_knowledge_files_cursor (PageInfiniteCursorData + writeable)."""
    class _Page:
        def model_dump(self):
            return {"data": [], "page_size": 10, "has_more": False, "next_cursor": None}

    async def _fake_query(knowledge_id):
        return _Row(KnowledgeTypeEnum.NORMAL.value)

    async def _fake_cursor(cls, request, login_user, knowledge_id, **kwargs):
        return _Page(), True

    monkeypatch.setattr(filelib.KnowledgeDao, "aquery_by_id", staticmethod(_fake_query))
    monkeypatch.setattr(KnowledgeService, "aget_knowledge_files_cursor", classmethod(_fake_cursor))

    resp = await filelib.get_filelist(
        request=None, knowledge_id=1, parent_id=None, keyword=None, status=None,
        page_size=10, cursor=None, user_id=None, version_repo=None, doc_repo=None,
    )
    assert resp.data["writeable"] is True
    assert "total" not in resp.data


async def test_filelist_dispatch_space(monkeypatch):
    """AC-27: space file list → list_space_children + can_write_space_container."""
    class _Page:
        def model_dump(self):
            return {"data": [], "page_size": 20, "has_more": False, "next_cursor": None}

    async def _fake_query(knowledge_id):
        return _Row(KnowledgeTypeEnum.SPACE.value)

    async def _fake_children(self, knowledge_id, **kwargs):
        return _Page()

    async def _fake_writeable(self, space_id, parent_id=None):
        return False

    monkeypatch.setattr(filelib.KnowledgeDao, "aquery_by_id", staticmethod(_fake_query))
    monkeypatch.setattr(KnowledgeSpaceService, "list_space_children", _fake_children)
    monkeypatch.setattr(KnowledgeSpaceService, "can_write_space_container", _fake_writeable)

    resp = await filelib.get_filelist(
        request=None, knowledge_id=7, parent_id=3, keyword=None, status=None,
        page_size=20, cursor=None, user_id=None, version_repo=None, doc_repo=None,
    )
    assert resp.data["writeable"] is False


# --------------------------------------------------------------------------- #
# T09 — delete / clear dispatch (regression)
# --------------------------------------------------------------------------- #
async def test_delete_dispatch_space(monkeypatch):
    """AC-30: deleting a space routes to KnowledgeSpaceService.delete_space (cascade)."""
    called = {}

    async def _fake_query(knowledge_id):
        return _Row(KnowledgeTypeEnum.SPACE.value)

    async def _fake_delete_space(self, space_id):
        called["space_id"] = space_id

    monkeypatch.setattr(filelib.KnowledgeDao, "aquery_by_id", staticmethod(_fake_query))
    monkeypatch.setattr(KnowledgeSpaceService, "delete_space", _fake_delete_space)

    resp = await filelib.delete_knowledge_api(
        request=None, knowledge_id=7, version_repo=None, doc_repo=None)
    assert called["space_id"] == 7
    assert "deleted" in resp.status_message.lower() or resp.status_code == 200


async def test_delete_dispatch_kb(monkeypatch):
    """AC-30: deleting a knowledge base routes to KnowledgeService.delete_knowledge."""
    called = {}

    async def _fake_query(knowledge_id):
        return _Row(KnowledgeTypeEnum.NORMAL.value)

    def _fake_delete(cls, request, login_user, knowledge_id):
        called["id"] = knowledge_id
        return True

    monkeypatch.setattr(filelib.KnowledgeDao, "aquery_by_id", staticmethod(_fake_query))
    monkeypatch.setattr(KnowledgeService, "delete_knowledge", classmethod(_fake_delete))

    await filelib.delete_knowledge_api(request=None, knowledge_id=1, version_repo=None, doc_repo=None)
    assert called["id"] == 1


async def test_clear_dispatch_space(monkeypatch):
    """AC-31: clearing a space routes to KnowledgeSpaceService.clear_space (keep space)."""
    called = {}

    async def _fake_query(knowledge_id):
        return _Row(KnowledgeTypeEnum.SPACE.value)

    async def _fake_clear_space(self, space_id):
        called["space_id"] = space_id

    monkeypatch.setattr(filelib.KnowledgeDao, "aquery_by_id", staticmethod(_fake_query))
    monkeypatch.setattr(KnowledgeSpaceService, "clear_space", _fake_clear_space)

    await filelib.clear_knowledge_files(request=None, knowledge_id=7, version_repo=None, doc_repo=None)
    assert called["space_id"] == 7


def _setup_delete_knowledge_mocks(monkeypatch, knowledge, qa_delete_spy):
    """Stub the heavy deps of KnowledgeService.delete_knowledge for unit testing."""
    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
    from bisheng.knowledge.domain.models.knowledge_file import QAKnoweldgeDao

    monkeypatch.setattr(KnowledgeDao, "query_by_id", classmethod(lambda cls, kid: knowledge))
    monkeypatch.setattr(KnowledgeDao, "delete_knowledge", classmethod(lambda cls, kid, only_clear=False: None))
    monkeypatch.setattr(KnowledgeService, "delete_knowledge_file_in_vector", classmethod(lambda cls, k: None))
    monkeypatch.setattr(KnowledgeService, "delete_knowledge_file_in_minio", classmethod(lambda cls, kid: None))
    monkeypatch.setattr(KnowledgeService.permission_service, "ensure_knowledge_delete_sync", lambda **kw: None)
    monkeypatch.setattr(KnowledgeService.audit_telemetry_service, "telemetry_delete_knowledge", lambda u: None)

    class _QA:
        def __init__(self, i):
            self.id = i

    monkeypatch.setattr(QAKnoweldgeDao, "get_qa_knowledge_by_knowledge_ids",
                        classmethod(lambda cls, kids: [_QA(11), _QA(12)]))
    monkeypatch.setattr(QAKnoweldgeDao, "delete_batch",
                        classmethod(lambda cls, ids: qa_delete_spy.update({"ids": ids})))


def test_clear_qa_removes_qa_rows(monkeypatch):
    """偏差6-QA: clearing a QA knowledge base also deletes its QAKnowledge rows."""
    qa = type("K", (), {"type": KnowledgeTypeEnum.QA.value, "user_id": 1, "id": 5})()
    spy = {}
    _setup_delete_knowledge_mocks(monkeypatch, qa, spy)
    KnowledgeService.delete_knowledge(request=None, login_user=_FakeUser(), knowledge_id=5, only_clear=True)
    assert spy.get("ids") == [11, 12]


def test_clear_normal_kb_skips_qa_rows(monkeypatch):
    """A document KB (type=0) clear must NOT touch the QAKnowledge table."""
    kb = type("K", (), {"type": KnowledgeTypeEnum.NORMAL.value, "user_id": 1, "id": 6})()
    spy = {}
    _setup_delete_knowledge_mocks(monkeypatch, kb, spy)
    KnowledgeService.delete_knowledge(request=None, login_user=_FakeUser(), knowledge_id=6, only_clear=True)
    assert "ids" not in spy  # QA delete path not taken


async def test_delete_rejects_type2(monkeypatch):
    """type=2 resource is not deletable via v2."""
    async def _fake_query(knowledge_id):
        return _Row(KnowledgeTypeEnum.PRIVATE.value)

    monkeypatch.setattr(filelib.KnowledgeDao, "aquery_by_id", staticmethod(_fake_query))
    with pytest.raises(HTTPException):
        await filelib.delete_knowledge_api(request=None, knowledge_id=5, version_repo=None, doc_repo=None)
