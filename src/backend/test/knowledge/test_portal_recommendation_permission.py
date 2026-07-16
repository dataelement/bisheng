import asyncio
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.services.portal_recommendation_service import (
    PortalRecommendationAuthorizationState,
    PortalRecommendationCandidate,
    PortalRecommendationPermissionContextUnavailable,
    PortalRecommendationService,
)


def _candidate(file_id: int, *, public: bool = False, eligible: bool = True):
    return PortalRecommendationCandidate(
        space_id=10,
        file_id=file_id,
        is_public=public,
        normal_acl=True,
        eligible=eligible,
    )


@pytest.mark.asyncio
async def test_authorization_is_progressive_in_batches_of_ten_and_keeps_order():
    batches: list[list[int]] = []

    async def build_context():
        return object()

    async def check_batch(_context, candidates):
        batches.append([item.file_id for item in candidates])
        return {item.key: item.file_id > 20 for item in candidates}

    selected = await PortalRecommendationService().select_authorized_top_n(
        [_candidate(file_id) for file_id in range(1, 31)],
        top_n=5,
        build_permission_context=build_context,
        check_permission_batch=check_batch,
    )

    assert [item.file_id for item in selected] == [21, 22, 23, 24, 25]
    assert [len(batch) for batch in batches] == [10, 10, 10]


@pytest.mark.asyncio
async def test_public_normal_files_use_fast_path_but_ineligible_or_custom_acl_do_not():
    checked: list[int] = []

    async def build_context():
        return object()

    async def check_batch(_context, candidates):
        checked.extend(item.file_id for item in candidates)
        return {item.key: False for item in candidates}

    candidates = [
        _candidate(1, public=True),
        _candidate(2, public=True, eligible=False),
        PortalRecommendationCandidate(space_id=10, file_id=3, is_public=True, normal_acl=False),
    ]
    selected = await PortalRecommendationService().select_authorized_top_n(
        candidates,
        top_n=3,
        build_permission_context=build_context,
        check_permission_batch=check_batch,
    )

    assert [item.file_id for item in selected] == [1]
    assert checked == [3]


@pytest.mark.asyncio
async def test_permission_context_failure_is_closed_as_an_empty_safe_result():
    async def build_context():
        raise PortalRecommendationPermissionContextUnavailable("permission engine unavailable")

    selected = await PortalRecommendationService().select_authorized_top_n(
        [_candidate(1)],
        top_n=1,
        build_permission_context=build_context,
        check_permission_batch=lambda *_args: None,
    )

    assert selected == []


@pytest.mark.asyncio
async def test_single_file_permission_exception_is_denied_without_aborting_later_candidates():
    async def build_context():
        return object()

    async def check_batch(_context, candidates):
        result = {}
        for item in candidates:
            result[item.key] = RuntimeError("do not leak metadata") if item.file_id == 1 else True
        return result

    selected = await PortalRecommendationService().select_authorized_top_n(
        [_candidate(1), _candidate(2)],
        top_n=2,
        build_permission_context=build_context,
        check_permission_batch=check_batch,
    )

    assert [item.file_id for item in selected] == [2]


@pytest.mark.asyncio
async def test_authorization_stops_at_two_hundred_checks_or_seven_hundred_ms():
    checked = 0

    async def build_context():
        return object()

    async def check_batch(_context, candidates):
        nonlocal checked
        checked += len(candidates)
        return {item.key: False for item in candidates}

    await PortalRecommendationService().select_authorized_top_n(
        [_candidate(file_id) for file_id in range(1, 301)],
        top_n=1,
        build_permission_context=build_context,
        check_permission_batch=check_batch,
    )
    assert checked == 200

    ticks = iter((0.0, 0.71))
    checked = 0
    await PortalRecommendationService(clock=lambda: next(ticks)).select_authorized_top_n(
        [_candidate(file_id) for file_id in range(1, 21)],
        top_n=1,
        build_permission_context=build_context,
        check_permission_batch=check_batch,
    )
    assert checked == 0


@pytest.mark.asyncio
async def test_batch_checker_system_failure_keeps_only_already_confirmed_public_items():
    async def build_context():
        return object()

    async def check_batch(_context, _candidates):
        await asyncio.sleep(0)
        raise PortalRecommendationPermissionContextUnavailable("request context lost")

    selected = await PortalRecommendationService().select_authorized_top_n(
        [_candidate(1, public=True), _candidate(2)],
        top_n=2,
        build_permission_context=build_context,
        check_permission_batch=check_batch,
    )

    assert [item.file_id for item in selected] == [1]


@pytest.mark.asyncio
async def test_reused_authorization_state_returns_prior_confirmed_items_after_check_cap():
    service = PortalRecommendationService()
    candidate = _candidate(1)
    state = PortalRecommendationAuthorizationState(
        started_at=0.0,
        checks=200,
        decisions={candidate.key: True},
        permission_context={},
        context_initialized=True,
    )

    selected = await service.select_authorized_top_n(
        [candidate],
        top_n=1,
        build_permission_context=AsyncMock(),
        check_permission_batch=AsyncMock(),
        state=state,
    )

    assert selected == [candidate]


@pytest.mark.asyncio
async def test_cached_recheck_and_full_rescore_share_one_request_check_budget():
    checked = 0
    state = PortalRecommendationAuthorizationState()

    async def build_context():
        return object()

    async def deny_batch(_context, candidates):
        nonlocal checked
        checked += len(candidates)
        return {candidate.key: False for candidate in candidates}

    service = PortalRecommendationService()
    await service.select_authorized_top_n(
        [_candidate(file_id) for file_id in range(1, 21)],
        top_n=1,
        build_permission_context=build_context,
        check_permission_batch=deny_batch,
        state=state,
    )
    await service.select_authorized_top_n(
        [_candidate(file_id) for file_id in range(21, 321)],
        top_n=1,
        build_permission_context=build_context,
        check_permission_batch=deny_batch,
        state=state,
    )

    assert checked == 200
    assert state.checks == 200
