"""Assignee row ids must cross the wire as strings.

Row ids are allocated as 60-62 bit integers (``secrets.randbits(62)`` for API
adds, ``sha256(...)[:15]`` for owner/copy paths), well past the 2^53 a JSON
number survives in a browser. Sent as a number, ``JSON.parse`` silently rounds
it and the id the client echoes back matches no assignee, so every REMOVE/MOVE
fails with "Grant assignee is missing or ambiguous".
"""

import json

import pytest
from pydantic import ValidationError

from bisheng.permission.domain.schemas.f048 import (
    GrantAssigneeDTO,
    GrantMutationChange,
)

# Both allocators produce ids in this range; 2**53 is the JS safe-integer limit.
UNSAFE_IDS = (
    2**53 + 1,
    4_611_686_018_427_387_903,  # secrets.randbits(62) upper bound
    1_152_921_504_606_846_975,  # int(sha256(...)[:15], 16) upper bound
)


@pytest.mark.parametrize("row_id", UNSAFE_IDS)
def test_remove_change_preserves_ids_beyond_js_safe_integers(row_id: int) -> None:
    change = GrantMutationChange.model_validate(
        {
            "op": "REMOVE",
            "assignee_id": str(row_id),
            "expected_assignee_version": 2,
        }
    )
    assert change.assignee_id == str(row_id)
    assert change.assignee_row_id == row_id


def test_numeric_assignee_id_is_rejected() -> None:
    """A number is the shape that loses precision in the browser."""

    with pytest.raises(ValidationError):
        GrantMutationChange.model_validate(
            {
                "op": "REMOVE",
                "assignee_id": 91,
                "expected_assignee_version": 2,
            }
        )


@pytest.mark.parametrize("bad", ["0", "-1", "01", "9e18", "", "12a"])
def test_assignee_id_must_be_a_positive_decimal_string(bad: str) -> None:
    with pytest.raises(ValidationError):
        GrantMutationChange.model_validate(
            {
                "op": "REMOVE",
                "assignee_id": bad,
                "expected_assignee_version": 2,
            }
        )


def test_add_still_rejects_an_assignee_identity() -> None:
    with pytest.raises(ValidationError):
        GrantMutationChange.model_validate(
            {
                "op": "ADD",
                "model_key": "standard-viewer",
                "subject": {"type": "user", "id": "7"},
                "assignee_id": "91",
            }
        )


@pytest.mark.parametrize("row_id", UNSAFE_IDS)
def test_roster_row_serializes_the_id_as_a_json_string(row_id: int) -> None:
    dto = GrantAssigneeDTO.model_validate(
        {
            "assignee_id": str(row_id),
            "assignee_version": 2,
            "subject": {"type": "user", "id": "7", "name": "Alice"},
            "model": {
                "key": "standard-viewer",
                "name": "Viewer",
                "level": 1,
                "active": True,
            },
            "source": {"type": "DIRECT", "include_children": False},
            "scope": "LOCAL",
            "inherited_from": None,
            "protected": False,
            "editable": True,
        }
    )
    payload = json.loads(dto.model_dump_json())
    assert payload["assignee_id"] == str(row_id)
    # Quoted in the raw JSON, so a browser never parses it as a number.
    assert f'"assignee_id":"{row_id}"' in dto.model_dump_json()
