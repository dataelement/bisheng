"""Tests for F026 KnowledgeFileVisibilityService.

Covers the three public methods that back the two-layer view_file filter:

- ``is_space_visible``       — non-throwing wrapper around the existing
  ``view_space`` gate (AC-11).
- ``build_index_prefilter``  — Milvus / ES filter strategy decision
  (AD-02 thresholds, AC-23 / AC-24 / AC-25 path selection).
- ``post_filter_visible_files`` — result-layer ``view_file`` filtering that
  drops chunks belonging to inaccessible files (AC-02 / AC-06 / AC-16 /
  AC-17 / AD-01 / AD-08).

OpenFGA is stubbed; Milvus / ES never run.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
    IndexFilter,
    KnowledgeFileVisibilityService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(
    *,
    is_admin: bool = False,
    user_id: int = 42,
) -> KnowledgeFileVisibilityService:
    """Build a service instance with mocked request + login_user."""
    login_user = MagicMock()
    login_user.user_id = user_id
    login_user.user_name = f"user-{user_id}"
    login_user.is_admin = MagicMock(return_value=is_admin)
    return KnowledgeFileVisibilityService(request=MagicMock(), login_user=login_user)


# ---------------------------------------------------------------------------
# is_space_visible — AC-11 short-circuits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_space_visible_true_when_view_space_granted(monkeypatch):
    """User holds view_space on the space → True."""
    svc = _make_service()

    space_svc_mock = MagicMock()
    space_svc_mock._require_read_permission = AsyncMock()
    space_svc_mock._require_permission_id = AsyncMock()
    monkeypatch.setattr(svc, "_space_service", lambda: space_svc_mock)

    assert await svc.is_space_visible(space_id=10) is True
    space_svc_mock._require_read_permission.assert_awaited_once_with(10)
    space_svc_mock._require_permission_id.assert_awaited_once_with(
        "knowledge_space", 10, "view_space"
    )


@pytest.mark.asyncio
async def test_is_space_visible_false_on_permission_denied(monkeypatch):
    """``SpacePermissionDeniedError`` from the gate → False, no propagation."""
    from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError

    svc = _make_service()
    space_svc_mock = MagicMock()
    space_svc_mock._require_read_permission = AsyncMock(
        side_effect=SpacePermissionDeniedError()
    )
    space_svc_mock._require_permission_id = AsyncMock()
    monkeypatch.setattr(svc, "_space_service", lambda: space_svc_mock)

    assert await svc.is_space_visible(space_id=10) is False


@pytest.mark.asyncio
async def test_is_space_visible_admin_passes(monkeypatch):
    """Admin user always sees every space; underlying gate calls still issue
    but they short-circuit inside PermissionService for admins, so we just
    assert the wrapper returns True without raising.
    """
    svc = _make_service(is_admin=True)
    space_svc_mock = MagicMock()
    space_svc_mock._require_read_permission = AsyncMock()
    space_svc_mock._require_permission_id = AsyncMock()
    monkeypatch.setattr(svc, "_space_service", lambda: space_svc_mock)

    assert await svc.is_space_visible(space_id=10) is True


# ---------------------------------------------------------------------------
# build_index_prefilter — AD-02 strategy matrix
# ---------------------------------------------------------------------------


def _patch_accessible_ids(monkeypatch, ids):
    """Patch PermissionService.list_accessible_ids to return ``ids`` (or None)."""
    from bisheng.permission.domain.services import permission_service

    async def fake(user_id, relation, object_type, login_user=None):  # noqa: ARG001
        return ids

    monkeypatch.setattr(
        permission_service.PermissionService, "list_accessible_ids", fake
    )


def _patch_space_primary_total(monkeypatch, total):
    """Patch the helper that counts primary file_ids in the space."""
    async def fake(self, space_id):  # noqa: ARG001
        return total

    monkeypatch.setattr(
        KnowledgeFileVisibilityService,
        "_count_primary_files_in_space",
        fake,
    )


def _patch_space_primary_ids(monkeypatch, ids):
    """Patch helper that lists primary file_ids in space (used when scoping
    the user's accessible_ids to the queried space).
    """
    async def fake(self, space_id):  # noqa: ARG001
        return set(ids)

    monkeypatch.setattr(
        KnowledgeFileVisibilityService,
        "_list_primary_file_ids_in_space",
        fake,
    )


@pytest.mark.asyncio
async def test_build_index_prefilter_empty_when_no_visible_files(monkeypatch):
    """K = 0 → strategy='empty', caller must skip retrieval entirely."""
    svc = _make_service()
    _patch_accessible_ids(monkeypatch, ["999"])  # accessible but not in this space
    _patch_space_primary_total(monkeypatch, 100)
    _patch_space_primary_ids(monkeypatch, {1, 2, 3, 4, 5})

    result = await svc.build_index_prefilter(space_id=10, candidate_file_ids=None)

    assert isinstance(result, IndexFilter)
    assert result.strategy == "empty"
    assert result.is_empty is True
    assert result.accessible_size == 0


@pytest.mark.asyncio
async def test_build_index_prefilter_in_when_small_visible_set(monkeypatch):
    """K small (≤ threshold) → strategy='in', expressions reference K ids only."""
    svc = _make_service()
    visible = [str(i) for i in range(1, 11)]  # K = 10
    _patch_accessible_ids(monkeypatch, visible)
    _patch_space_primary_total(monkeypatch, 1000)
    _patch_space_primary_ids(monkeypatch, set(range(1, 1001)))

    result = await svc.build_index_prefilter(space_id=10, candidate_file_ids=None)

    assert result.strategy == "in"
    assert result.is_empty is False
    assert result.accessible_size == 10
    assert result.milvus_expr is not None
    assert "document_id in " in result.milvus_expr
    assert result.es_filter is not None
    # Sanity: only the 10 visible ids appear, none of the others
    for vid in [1, 2, 10]:
        assert str(vid) in result.milvus_expr
    assert " 1000" not in result.milvus_expr  # an out-of-set id must not leak


@pytest.mark.asyncio
async def test_build_index_prefilter_notin_when_almost_everything_visible(monkeypatch):
    """N - K ≤ threshold (and K > threshold) → strategy='notin' with the
    complement set.
    """
    svc = _make_service()
    # K = 9997 visible, total N = 10000 → complement = 3 ids
    visible_ids = [str(i) for i in range(1, 9998)]
    _patch_accessible_ids(monkeypatch, visible_ids)
    _patch_space_primary_total(monkeypatch, 10000)
    _patch_space_primary_ids(monkeypatch, set(range(1, 10001)))

    result = await svc.build_index_prefilter(space_id=10, candidate_file_ids=None)

    assert result.strategy == "notin"
    assert result.is_empty is False
    assert result.accessible_size == 9997
    assert result.milvus_expr is not None
    assert "not in" in result.milvus_expr
    # The complement (9998, 9999, 10000) is what's excluded
    assert "9998" in result.milvus_expr
    assert "10000" in result.milvus_expr


@pytest.mark.asyncio
async def test_build_index_prefilter_none_when_both_sides_too_large(monkeypatch):
    """K > threshold AND N - K > threshold → strategy='none', skip index
    pushdown; result layer will carry the burden.
    """
    svc = _make_service()
    visible_ids = [str(i) for i in range(1, 20001)]  # K = 20000
    _patch_accessible_ids(monkeypatch, visible_ids)
    _patch_space_primary_total(monkeypatch, 100000)
    _patch_space_primary_ids(monkeypatch, set(range(1, 100001)))

    result = await svc.build_index_prefilter(space_id=10, candidate_file_ids=None)

    assert result.strategy == "none"
    assert result.is_empty is False
    assert result.milvus_expr is None
    assert result.es_filter is None


@pytest.mark.asyncio
async def test_build_index_prefilter_admin_short_circuits(monkeypatch):
    """``list_accessible_ids`` returns None for admin → strategy='none',
    no filter; admin sees everything.
    """
    svc = _make_service(is_admin=True)
    _patch_accessible_ids(monkeypatch, None)

    result = await svc.build_index_prefilter(space_id=10, candidate_file_ids=None)

    assert result.strategy == "none"
    assert result.is_empty is False
    assert result.milvus_expr is None
    assert result.es_filter is None
    assert result.accessible_size == 0  # admin sentinel; not used by callers


@pytest.mark.asyncio
async def test_build_index_prefilter_intersects_candidate_ids(monkeypatch):
    """When candidate_file_ids is provided (folder / tag scope), the K used
    for strategy selection is the intersection of accessible × candidate.
    """
    svc = _make_service()
    _patch_accessible_ids(monkeypatch, [str(i) for i in range(1, 1001)])
    _patch_space_primary_total(monkeypatch, 1000)
    _patch_space_primary_ids(monkeypatch, set(range(1, 1001)))

    # Candidate only includes 3 ids → K reduced to 3
    result = await svc.build_index_prefilter(
        space_id=10, candidate_file_ids=[5, 6, 7]
    )

    assert result.strategy == "in"
    assert result.accessible_size == 3
    assert "5" in result.milvus_expr
    assert "6" in result.milvus_expr
    assert "7" in result.milvus_expr


# ---------------------------------------------------------------------------
# post_filter_visible_files — AD-01 / AD-08
# ---------------------------------------------------------------------------


def _patch_effective_permissions(
    monkeypatch,
    space_svc_mock,
    allowed_file_ids: set[int],
):
    """Wire the mock KnowledgeSpaceService so its
    ``_get_child_item_effective_permission_ids`` returns ``{'view_file'}``
    for ids in ``allowed_file_ids`` and ``set()`` elsewhere; also patch
    ``KnowledgeFileDao.aget_file_by_ids`` (real class) to yield synthetic
    KnowledgeFile-like items with ``id`` + ``file_type`` attributes.
    """
    from bisheng.knowledge.domain.models import knowledge_file as kf_module

    async def fake_aget(cls, file_ids):  # noqa: ARG001
        return [MagicMock(id=int(fid), file_type=1) for fid in file_ids]

    monkeypatch.setattr(
        kf_module.KnowledgeFileDao,
        "aget_file_by_ids",
        classmethod(fake_aget),
    )

    async def fake_effective(item, *, space_id, context):  # noqa: ARG001
        return {"view_file"} if int(item.id) in allowed_file_ids else set()

    space_svc_mock._get_child_item_effective_permission_ids = AsyncMock(
        side_effect=fake_effective
    )


@pytest.mark.asyncio
async def test_post_filter_visible_files_keeps_only_permitted(monkeypatch):
    """30 input file_ids, 10 grant view_file → exactly those 10 returned."""
    svc = _make_service()
    space_svc_mock = MagicMock()
    space_svc_mock._build_child_permission_context = AsyncMock(
        return_value={"models": {}, "bindings": [], "tuple_cache": {}}
    )
    monkeypatch.setattr(svc, "_space_service", lambda: space_svc_mock)

    inputs = set(range(1, 31))
    allowed = {3, 7, 11, 13, 17, 19, 23, 25, 27, 29}  # 10 ids
    _patch_effective_permissions(monkeypatch, space_svc_mock, allowed)

    result = await svc.post_filter_visible_files(space_id=10, file_ids=inputs)

    assert result == allowed


@pytest.mark.asyncio
async def test_post_filter_visible_files_admin_returns_all(monkeypatch):
    """Admin short-circuit: skip fine-grained calls entirely, return input as-is."""
    svc = _make_service(is_admin=True)

    inputs = {1, 2, 3, 4, 5}
    result = await svc.post_filter_visible_files(space_id=10, file_ids=inputs)

    assert result == inputs


@pytest.mark.asyncio
async def test_post_filter_visible_files_empty_input_short_circuits(monkeypatch):
    """Empty input set → empty output, no context build, no FGA calls."""
    svc = _make_service()
    space_svc_mock = MagicMock()
    space_svc_mock._build_child_permission_context = AsyncMock()
    monkeypatch.setattr(svc, "_space_service", lambda: space_svc_mock)

    result = await svc.post_filter_visible_files(space_id=10, file_ids=set())

    assert result == set()
    space_svc_mock._build_child_permission_context.assert_not_called()


@pytest.mark.asyncio
async def test_post_filter_visible_files_concurrent_load_completes(monkeypatch):
    """50 file_ids run through the semaphore-limited gather without deadlocking
    and produce a correct subset.
    """
    svc = _make_service()
    space_svc_mock = MagicMock()
    space_svc_mock._build_child_permission_context = AsyncMock(
        return_value={"models": {}, "bindings": [], "tuple_cache": {}}
    )
    monkeypatch.setattr(svc, "_space_service", lambda: space_svc_mock)

    inputs = set(range(1, 51))
    allowed = {i for i in inputs if i % 2 == 0}  # 25 ids
    _patch_effective_permissions(monkeypatch, space_svc_mock, allowed)

    result = await svc.post_filter_visible_files(space_id=10, file_ids=inputs)

    assert result == allowed


@pytest.mark.asyncio
async def test_post_filter_visible_files_regression_revoke_overrides_membership(monkeypatch):
    """Regression: ensure file-level revoke wins over space-membership default.

    Reproduces the production bug where a user with space-membership view_file
    saw revoked files leak into AI Q&A retrieval because the old impl
    omitted ``nearest_binding_wins=True`` + the membership/public defaults
    when calling ``FineGrainedPermissionService``. Delegating to
    ``KnowledgeSpaceService._get_child_item_effective_permission_ids``
    restores the same semantics the listing UI uses (INV-6).
    """
    svc = _make_service()
    space_svc_mock = MagicMock()
    space_svc_mock._build_child_permission_context = AsyncMock(
        return_value={"models": {}, "bindings": [], "tuple_cache": {}}
    )
    monkeypatch.setattr(svc, "_space_service", lambda: space_svc_mock)

    # 5 files in the space; admin revoked view_file on {1, 2, 3, 4} via per-file
    # bindings. Only file 5 keeps the membership default. The delegated
    # _get_child_item_effective_permission_ids returns {'view_file'} only for 5.
    _patch_effective_permissions(monkeypatch, space_svc_mock, {5})

    result = await svc.post_filter_visible_files(
        space_id=3565, file_ids={1, 2, 3, 4, 5}
    )

    assert result == {5}, (
        "Expected only the non-revoked file to survive; got "
        f"{sorted(result)} — the canonical lineage + nearest_binding_wins "
        "semantics are not being applied."
    )
