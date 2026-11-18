"""Conflict copy reflects observed state without exposing job internals."""

import pytest

from bisheng.knowledge.domain.schemas.processing_diagnostics import file_processing_conflict, space_processing_conflict


@pytest.mark.parametrize(
    "state,transition,operation",
    [
        (0, False, "space_unpublished"),
        (2, False, "space_copy"),
        (3, False, "embedding_rebuild"),
        (1, True, "embedding_rebuild"),
        (4, False, "space_failed"),
        (99, False, None),
    ],
)
def test_space_lifecycle_conflicts_preserve_reason(state, transition, operation):
    error = space_processing_conflict("processing_space_not_ready", state=state, has_transition=transition)
    assert error.Code == 10999
    assert error.kwargs["reason"] == "processing_space_not_ready"
    assert error.kwargs.get("blocking_operation") == operation
    assert set(error.kwargs) <= {"reason", "blocking_operation"}


@pytest.mark.parametrize(
    "status,operation",
    [(1, "file_parse"), (4, "embedding_rebuild"), (5, "file_waiting"), (0, None), (3, None), (999, None)],
)
def test_file_conflicts_do_not_mislabel_unknown_or_failed_status_as_parsing(status, operation):
    error = file_processing_conflict("processing_file_state_not_ready", status)
    assert error.kwargs.get("blocking_operation") == operation
