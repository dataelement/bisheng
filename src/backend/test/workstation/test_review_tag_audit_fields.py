"""F079 T004: audit trail written when a tag is approved or rejected.

Before F079 nobody recorded *who* reviewed a tag. ``review_tag`` had a
``review_time`` but no reviewer, and ``tag`` had neither — so approving a tag,
which moves the row out of ``review_tag`` and into ``tag``, erased the trail.

Two things drove the design here and are asserted below:

- **Approve hard-deletes the ``review_tag`` row** (``approve_review_tag``), so the
  reviewer must be stamped onto the ``tag`` row during the move. Writing it back
  to ``review_tag`` would be pointless — nothing survives to read it from.
- ``review_time`` is still ``None`` on the source row at move time (the service
  moves first, marks the review afterwards), so the ``tag`` row takes the
  reviewer and timestamp passed in by the caller, not a copy of the source.
"""

import importlib
import sys
import types
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

base_service_stub = types.ModuleType("bisheng.common.services.base")


class _BaseService:
    pass


base_service_stub.BaseService = _BaseService
sys.modules["bisheng.common.services.base"] = base_service_stub
workstation_tags_service = importlib.reload(
    importlib.import_module("bisheng.workstation.domain.services.workstation_tags_service")
)

from bisheng.database.models.review_tags import ReviewTag, ReviewTagLink  # noqa: E402
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagResourceTypeEnum  # noqa: E402
from bisheng.workstation.domain.repositories.tags_repository import TagRepositoryImpl  # noqa: E402

REVIEWER_ID = 77
SUBMITTER_ID = 42
REVIEWED_AT = datetime(2026, 8, 7, 10, 30, 0)


def _pending_review_tag() -> ReviewTag:
    return ReviewTag(
        id=1,
        name="结垢",
        business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
        business_id="10",
        user_id=SUBMITTER_ID,
        tenant_id=1,
        resource_type=TagResourceTypeEnum.AI_AUTO_TAG.value,
        create_time=datetime(2026, 8, 5, 9, 0, 0),
        update_time=datetime(2026, 8, 5, 9, 0, 0),
        review_status=0,
        review_time=None,
    )


def _review_tag_link() -> ReviewTagLink:
    return ReviewTagLink(
        id=1,
        tag_id=1,
        resource_id="501",
        resource_type=1,
        user_id=SUBMITTER_ID,
        tenant_id=1,
        create_time=datetime(2026, 8, 5, 9, 0, 0),
        update_time=datetime(2026, 8, 5, 9, 0, 0),
    )


def _added_tag(session: MagicMock) -> Tag:
    """Pull the Tag instance handed to ``session.add`` during the move."""
    tags = [call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], Tag)]
    assert len(tags) == 1, f"expected exactly one Tag insert, got {len(tags)}"
    return tags[0]


def _build_tag_repository() -> tuple[TagRepositoryImpl, MagicMock]:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return TagRepositoryImpl(session=session), session


@pytest.mark.asyncio
async def test_approve_stamps_reviewer_on_moved_tag():
    repository, session = _build_tag_repository()

    await repository.approve_tag_to_move(
        _pending_review_tag(),
        [_review_tag_link()],
        reviewer_id=REVIEWER_ID,
        review_time=REVIEWED_AT,
    )

    tag = _added_tag(session)
    assert tag.reviewer_id == REVIEWER_ID
    assert tag.review_time == REVIEWED_AT


@pytest.mark.asyncio
async def test_approve_preserves_submitter():
    """The reviewer must not overwrite who originally proposed the tag."""
    repository, session = _build_tag_repository()

    await repository.approve_tag_to_move(
        _pending_review_tag(),
        [_review_tag_link()],
        reviewer_id=REVIEWER_ID,
        review_time=REVIEWED_AT,
    )

    tag = _added_tag(session)
    assert tag.user_id == SUBMITTER_ID
    assert tag.name == "结垢"
    assert tag.business_id == "10"
    assert tag.resource_type == TagResourceTypeEnum.AI_AUTO_TAG.value


@pytest.mark.asyncio
async def test_approve_without_reviewer_leaves_audit_fields_empty():
    """Callers that predate F079 keep working; the columns just stay null."""
    repository, session = _build_tag_repository()

    await repository.approve_tag_to_move(_pending_review_tag(), [_review_tag_link()])

    tag = _added_tag(session)
    assert tag.reviewer_id is None
    assert tag.review_time is None


def _literal(value):
    """SQLAlchemy wraps update() values in BindParameter; unwrap to the raw value."""
    return getattr(value, "value", value)


def _reject_update_values(session: MagicMock) -> dict:
    """Collect the values() payload of the ReviewTag update issued by reject."""
    payloads = []
    for call in session.exec.call_args_list:
        statement = call.args[0]
        values = getattr(statement, "_values", None)
        if not values:
            continue
        payload = {getattr(column, "name", str(column)): _literal(value) for column, value in values.items()}
        if "review_status" in payload:
            payloads.append(payload)
    assert len(payloads) == 1, f"expected exactly one ReviewTag status update, got {len(payloads)}"
    return payloads[0]


@pytest.mark.asyncio
async def test_reject_stamps_reviewer_and_reason():
    """Reject soft-deletes the row, so the trail does live on ``review_tag`` here."""
    from bisheng.workstation.domain.repositories.review_tags_repository import ReviewTagsRepositoryImpl

    session = MagicMock()
    session.exec = AsyncMock()
    repository = ReviewTagsRepositoryImpl(session=session, tags_repository=MagicMock())
    repository.get_review_tag_list_by_tag_name = AsyncMock(return_value=[_pending_review_tag()])

    await repository.reject_review_tag(
        "结垢",
        "不建议新增",
        TagResourceTypeEnum.AI_AUTO_TAG,
        tenant_id=1,
        reviewer_id=REVIEWER_ID,
    )

    values = _reject_update_values(session)
    assert values["reviewer_id"] == REVIEWER_ID
    assert values["reject_reason"] == "不建议新增"
    assert values["review_time"] is not None


@pytest.mark.asyncio
async def test_service_passes_login_user_as_reviewer():
    """End of the chain: the service is what knows who is logged in."""
    WorkStationTagsService = workstation_tags_service.WorkStationTagsService

    session = AsyncMock()
    service = WorkStationTagsService(
        request=MagicMock(),
        session=session,
        login_user=SimpleNamespace(
            user_id=REVIEWER_ID,
            tenant_id=1,
            is_global_super=True,
            is_admin=lambda: True,
            user_name="reviewer",
        ),
        review_tags_repository=AsyncMock(),
    )
    service.review_tags_repository.get_review_tag_list_by_tag_name = AsyncMock(
        return_value=[_pending_review_tag()],
    )
    service.review_tags_repository.query_existed_tag_by_review_tag = AsyncMock(return_value=None)
    service.review_tags_repository.query_review_tag_link_list_by_tag_id = AsyncMock(
        return_value=[_review_tag_link()],
    )
    service.review_tags_repository.approve_tag_to_move = AsyncMock()

    await service.approve_tag_to_move_operation(
        "结垢",
        TagResourceTypeEnum.AI_AUTO_TAG,
        tenant_id=1,
        skip_library_add=True,
    )

    service.review_tags_repository.approve_tag_to_move.assert_awaited_once()
    kwargs = service.review_tags_repository.approve_tag_to_move.await_args.kwargs
    assert kwargs["reviewer_id"] == REVIEWER_ID
    assert kwargs["review_time"] is not None
