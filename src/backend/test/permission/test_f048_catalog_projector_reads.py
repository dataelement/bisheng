"""Catalog publish reads OpenFGA in proportion to the plan, not the Store.

Both staging and verification used to issue an unfiltered Read, which walks the
whole Store 100 tuples per request. On a 77k-tuple Store that is ~774 round
trips each, at HIGHER_CONSISTENCY — one observed publish spent 423s and then
died at its commit step, where a filter without an object type earned a generic
OpenFGA validation_error.
"""

from __future__ import annotations

import pytest

from bisheng.permission.application.catalog_api import OpenFGACatalogProjector


class _RecordingClient:
    """Answer Reads from a tiny Store and record exactly how they were filtered."""

    def __init__(self, tuples: set[tuple[str, str, str]]) -> None:
        self.store_id = "store-1"
        self.model_id = "model-f048"
        self.tuples = tuples
        self.read_filters: list[dict[str, str | None]] = []

    async def read_tuples(
        self,
        user: str | None = None,
        relation: str | None = None,
        object: str | None = None,
        consistency: str | None = None,
    ) -> list[dict]:
        del consistency
        self.read_filters.append({"user": user, "relation": relation, "object": object})
        if object is not None and not object.partition(":")[0]:
            raise AssertionError(f"read filter without an object type: {object!r}")
        if object is not None and object.endswith(":") and not user:
            raise AssertionError("type-only object filter needs a user")
        matched = [
            {"user": row_user, "relation": row_relation, "object": row_object}
            for row_user, row_relation, row_object in sorted(self.tuples)
            if (user is None or row_user == user)
            and (relation is None or row_relation == relation)
            and (object is None or row_object == object or (object.endswith(":") and row_object.startswith(object)))
        ]
        return matched


PLANNED = [
    {"user": "permission_model_release:r1", "relation": "release", "object": "permission_model:viewer"},
    {"user": "permission_catalog_release:c1", "relation": "catalog", "object": "permission_model_release:r1"},
    {"user": "user:*", "relation": "enabled_marker", "object": "permission_model_release:r1"},
]

# Everything a real Store also holds and a publish has no business reading.
UNRELATED = {("user:9", "ordinary_assignee", f"permission_grant:g{index}") for index in range(500)}


def _projector(client: _RecordingClient) -> OpenFGACatalogProjector:
    return OpenFGACatalogProjector(client=client, marker=None)


@pytest.mark.asyncio
async def test_present_reads_only_the_planned_objects() -> None:
    present_rows = {(row["user"], row["relation"], row["object"]) for row in PLANNED[:2]}
    client = _RecordingClient(present_rows | UNRELATED)

    present = await _projector(client)._read_present(PLANNED)

    assert present == present_rows
    # One Read per distinct planned object — never an unfiltered Store walk.
    assert len(client.read_filters) == 2
    assert {entry["object"] for entry in client.read_filters} == {
        "permission_model:viewer",
        "permission_model_release:r1",
    }
    assert all(entry["object"] for entry in client.read_filters)


@pytest.mark.asyncio
async def test_present_is_empty_without_a_plan() -> None:
    client = _RecordingClient(UNRELATED)

    assert await _projector(client)._read_present([]) == set()
    assert client.read_filters == []


@pytest.mark.asyncio
async def test_active_release_keys_filter_names_the_object_type() -> None:
    client = _RecordingClient({("user:*", "active", "permission_catalog_release:c1")} | UNRELATED)

    assert await _projector(client).read_active_release_keys() == frozenset({"c1"})

    assert client.read_filters == [
        {
            "user": "user:*",
            "relation": "active",
            "object": "permission_catalog_release:",
        }
    ]
