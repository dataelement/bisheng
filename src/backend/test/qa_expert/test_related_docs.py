# ruff: noqa: RUF002
"""T020：关联文档详情不挡正文；无权 forbidden 不得写成 not_found。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bisheng.qa_expert.domain.services import QuestionService


def _service() -> QuestionService:
    svc = QuestionService()
    svc.repository = MagicMock()
    svc.invite_repo = MagicMock()
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={})
    svc.answer_repo = MagicMock()
    svc.expert_repo = MagicMock()
    svc.expert_repo.get_by_user_id = AsyncMock(return_value=None)
    svc.expert_repo.get_by_ids = AsyncMock(return_value=[])
    svc.eligibility_repo = MagicMock()
    svc.eligibility_repo.list_user_ids = AsyncMock(return_value=set())
    svc.publish_request_repo = MagicMock()
    svc.publish_request_repo.get_pending_by_question = AsyncMock(return_value=None)
    svc.publish_request_repo.get_latest_by_question = AsyncMock(return_value=None)
    svc.publish_approver_repo = MagicMock()
    svc.publish_approver_repo.list_by_request = AsyncMock(return_value=[])
    svc._resolve_question = AsyncMock(side_effect=lambda q: q)
    svc.answer_repo.has_effective_answer = AsyncMock(return_value=False)
    svc.identity_service = SimpleNamespace(
        mask_identity=AsyncMock(
            return_value=SimpleNamespace(
                to_dict=lambda **_: {"display_name": "u", "anonymous": False, "avatar_url": None}
            )
        )
    )
    return svc


async def test_detail_always_returns_question_body_when_doc_forbidden(monkeypatch):
    monkeypatch.setattr(
        "bisheng.qa_expert.domain.publish_service.PublishService.refresh_latest_for_question",
        AsyncMock(return_value=None),
    )
    svc = _service()
    question = SimpleNamespace(
        id=3,
        user_id=1,
        title="正文仍在",
        description="可见描述",
        question_type="public",
        related_docs="12-99",
        view_count=0,
        adopt_count=0,
        answer_count=0,
    )
    svc.repository.get_by_id = AsyncMock(return_value=question)
    svc.repository.update = AsyncMock()

    async def checker(_user, space_id, file_id):
        assert (space_id, file_id) == (12, 99)
        return False

    svc.related_docs_access_checker = checker
    detail = await svc.get_question_detail(
        3, user_id=2, user=SimpleNamespace(user_id=2, is_admin=lambda: False, role=None)
    )
    assert detail.title == "正文仍在"
    assert detail.description == "可见描述"
    view = detail.related_doc_views[0]
    assert view["id"] == "12-99"
    assert view["accessible"] is False
    assert view["unavailable_reason"] == "forbidden"
    assert view["unavailable_reason"] != "not_found"


async def test_accessible_doc_keeps_durable_id():
    svc = _service()

    async def checker(_user, _s, _f):
        return True

    svc.related_docs_access_checker = checker
    views = await svc.hydrate_related_docs("8-15")
    assert views[0]["id"] == "8-15"
    assert views[0]["space_id"] == 8
    assert views[0]["file_id"] == 15
    assert views[0]["accessible"] is True
    assert views[0]["unavailable_reason"] is None


async def test_non_owner_with_permission_is_accessible():
    """有库权限的路人可点链接，不再因不是提问者一律 forbidden。"""
    svc = _service()

    async def checker(_user, _s, _f):
        return True

    svc.related_docs_access_checker = checker
    views = await svc.hydrate_related_docs(
        "8-15",
        user=SimpleNamespace(user_id=2),
        owner_user_id=1,
    )
    assert views[0]["accessible"] is True
    assert views[0]["unavailable_reason"] is None


async def test_owner_without_permission_is_forbidden():
    """提问者无知识库权限时不可点，不再因是作者特判放行。"""
    svc = _service()

    async def checker(_user, _s, _f):
        return False

    svc.related_docs_access_checker = checker
    views = await svc.hydrate_related_docs(
        "8-15",
        user=SimpleNamespace(user_id=1),
        owner_user_id=1,
    )
    assert views[0]["accessible"] is False
    assert views[0]["unavailable_reason"] == "forbidden"


async def test_owner_existing_file_is_accessible():
    svc = _service()

    async def checker(_user, _s, _f):
        return True

    svc.related_docs_access_checker = checker
    views = await svc.hydrate_related_docs(
        "8-15",
        user=SimpleNamespace(user_id=1),
        owner_user_id=1,
    )
    assert views[0]["accessible"] is True
    assert views[0]["unavailable_reason"] is None


async def test_missing_file_is_not_found_not_forbidden():
    svc = _service()

    async def checker(_user, _s, _f):
        return None

    svc.related_docs_access_checker = checker
    views = await svc.hydrate_related_docs("8-404")
    assert views[0]["accessible"] is False
    assert views[0]["unavailable_reason"] == "not_found"


async def test_hung_access_check_is_forbidden_not_500(monkeypatch):
    """鉴权挂起时详情仍返回正文，文档记 forbidden 而不是把整页拖死。"""
    import asyncio

    from bisheng.qa_expert.domain import related_docs_access

    monkeypatch.setattr(related_docs_access, "RELATED_DOC_ACCESS_TIMEOUT_SEC", 0.05)
    svc = _service()

    async def checker(_user, _s, _f):
        await asyncio.sleep(2)
        return True

    svc.related_docs_access_checker = checker
    views = await svc.hydrate_related_docs("8-15")
    assert views[0]["accessible"] is False
    assert views[0]["unavailable_reason"] == "forbidden"


async def test_hydrate_fills_title_from_knowledge_file(monkeypatch):
    """关联文档展示名走 knowledgefile.file_name，不能只回 space-file id。"""
    from bisheng.qa_expert.domain import related_docs_access

    monkeypatch.setattr(
        related_docs_access,
        "load_related_doc_title",
        AsyncMock(return_value="炼钢规程.pdf"),
    )
    svc = _service()

    async def checker(_user, _s, _f):
        return True

    svc.related_docs_access_checker = checker
    views = await svc.hydrate_related_docs("8-15")
    assert views[0]["id"] == "8-15"
    assert views[0]["title"] == "炼钢规程.pdf"
