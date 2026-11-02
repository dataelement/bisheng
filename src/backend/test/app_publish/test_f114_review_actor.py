"""A single configured candidate never proves a single tenant administrator."""

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def candidates(monkeypatch):
    from bisheng.approval.application import app_candidates as mod

    admins = {81, 42}
    monkeypatch.setattr(mod, "administrator_ids", AsyncMock(side_effect=lambda tenant: tuple(admins)))
    monkeypatch.setattr(
        mod.AppCandidateRepository, "eligible_ids", AsyncMock(side_effect=lambda tenant, values, **kw: tuple(values))
    )
    return mod, admins


async def test_dual_exclusion_and_deduplication(candidates):
    mod, _admins = candidates
    result = await mod.qualify_app_candidates(3, 81, 42, [81, 42, 99, 99])
    assert result.user_ids == (99,) and not result.self_approval


async def test_one_configured_candidate_with_two_admins_is_not_exception(candidates):
    mod, _admins = candidates
    assert (await mod.qualify_app_candidates(3, 81, 81, [81])).user_ids == ()


async def test_verified_single_admin_can_self_review(candidates):
    mod, admins = candidates
    admins.clear()
    admins.add(81)
    result = await mod.qualify_app_candidates(3, 81, 81, [81])
    assert result.user_ids == (81,) and result.self_approval
    assert (await mod.qualify_app_candidates(3, 81, 42, [81, 42])).user_ids == ()


async def test_unknown_frozen_submitter_does_not_guess_owner(candidates):
    mod, _admins = candidates
    assert (await mod.qualify_app_candidates(3, 81, None, [99])).user_ids == ()


async def test_administrator_dependency_failure_never_enables_exception(candidates):
    mod, _admins = candidates
    mod.administrator_ids.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError):
        await mod.qualify_app_candidates(3, 81, 81, [81])
