"""A candidate row the scan found must actually get repaired.

`_repair_single` compared the freshly loaded permission record against the
expectation computed from the same `file_level_path` — two readings of the same
business truth, so always equal — and skipped every candidate as "already
consistent". Production said it plainly:

    found 1 stale rows (root=1, nested=0)
    resource knowledge_file/1113 already consistent, skipping
    repaired 0 out of 1 stale rows
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.services import stale_projection_reconciler as reconciler


@dataclass(frozen=True)
class _Record:
    """Only the fields the repair touches; `replace()` needs a dataclass."""

    resource_type: str
    resource_id: str
    parent_type: str
    parent_id: str


_SPACE_PARENT = ("knowledge_space", "152")
_FOLDER_PARENT = ("folder", "1110")


def _adapter(record):
    return SimpleNamespace(
        load_permission_record=AsyncMock(return_value=record),
        project_move=AsyncMock(return_value=None),
    )


async def _repair(adapter, *, stored, correct):
    with patch.object(reconciler, "get_f048_resource_adapter", AsyncMock(return_value=adapter)):
        return await reconciler._repair_single(
            resource_type="knowledge_file",
            resource_id="1113",
            stored_parent_type=stored[0],
            stored_parent_id=stored[1],
            tenant_id=1,
            correct_parent_type=correct[0],
            correct_parent_id=correct[1],
        )


async def test_a_drifted_mirror_is_repaired():
    """The reported case: mirror says the old folder, the file sits at the root."""
    record = _Record("knowledge_file", "1113", *_SPACE_PARENT)
    adapter = _adapter(record)

    assert await _repair(adapter, stored=_FOLDER_PARENT, correct=_SPACE_PARENT) is True

    adapter.project_move.assert_awaited_once()
    kwargs = adapter.project_move.await_args.kwargs
    # Moving *from* what the mirror wrongly holds *to* the business truth.
    assert (kwargs["source"].parent_type, kwargs["source"].parent_id) == _FOLDER_PARENT
    assert (kwargs["target"].parent_type, kwargs["target"].parent_id) == _SPACE_PARENT


async def test_a_mirror_that_already_agrees_is_left_alone():
    record = _Record("knowledge_file", "1113", *_SPACE_PARENT)
    adapter = _adapter(record)

    assert await _repair(adapter, stored=_SPACE_PARENT, correct=_SPACE_PARENT) is False

    adapter.project_move.assert_not_awaited()


async def test_a_file_that_moved_again_since_the_scan_is_left_for_next_cycle():
    """Writing the scan's stale expectation over a newer truth would be worse."""
    record = _Record("knowledge_file", "1113", "folder", "9999")
    adapter = _adapter(record)

    assert await _repair(adapter, stored=_FOLDER_PARENT, correct=_SPACE_PARENT) is False

    adapter.project_move.assert_not_awaited()


async def test_a_vanished_resource_is_skipped():
    adapter = _adapter(None)

    assert await _repair(adapter, stored=_FOLDER_PARENT, correct=_SPACE_PARENT) is False

    adapter.project_move.assert_not_awaited()


@pytest.mark.parametrize(
    ("path", "knowledge_id", "expected"),
    [("", 152, _SPACE_PARENT), ("/1110/", 152, _FOLDER_PARENT)],
)
def test_the_expectation_the_repair_is_handed_comes_from_the_path(path, knowledge_id, expected):
    assert reconciler._compute_correct_parent(path, knowledge_id) == expected
