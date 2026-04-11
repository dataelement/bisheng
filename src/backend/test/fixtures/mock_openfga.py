"""In-memory OpenFGA mock for unit tests.

Stores tuples as (object, relation, user) triples in a Python set.
Supports basic WriteTuples, DeleteTuples, Check, ListObjects, ListUsers.
Does NOT implement userset expansion (transitive resolution via Zanzibar).

F004-rebac-core will define the real FGAClient. This mock provides the
interface contract so F002-F008 tests have a fixture available immediately.
Update this mock to match the real client interface when F004 lands.

All methods are async to match the expected async client interface.

Created by F000-test-infrastructure.
"""

from __future__ import annotations


class InMemoryOpenFGAClient:
    """Pure in-memory OpenFGA mock for testing."""

    def __init__(self) -> None:
        self._tuples: set[tuple[str, str, str]] = set()

    # ----- Write operations -----

    async def write_tuples(self, writes: list[dict]) -> None:
        """Write authorization tuples.

        Each item in writes must have keys: object, relation, user.
        Example: {"object": "workflow:wf-1", "relation": "viewer", "user": "user:alice"}
        """
        for item in writes:
            self._tuples.add((item['object'], item['relation'], item['user']))

    async def delete_tuples(self, deletes: list[dict]) -> None:
        """Delete authorization tuples."""
        for item in deletes:
            self._tuples.discard((item['object'], item['relation'], item['user']))

    # ----- Check operations -----

    async def check(self, user: str, relation: str, object: str) -> bool:
        """Check if user has relation to object (direct match only)."""
        return (object, relation, user) in self._tuples

    # ----- List operations -----

    async def list_objects(self, user: str, relation: str, type: str) -> list[str]:
        """List all objects of given type that user has relation to."""
        prefix = f'{type}:'
        return [
            obj for obj, rel, usr in self._tuples
            if usr == user and rel == relation and obj.startswith(prefix)
        ]

    async def list_users(self, relation: str, object: str, user_type: str) -> list[str]:
        """List all users of given type that have relation to object."""
        prefix = f'{user_type}:'
        return [
            usr for obj, rel, usr in self._tuples
            if obj == object and rel == relation and usr.startswith(prefix)
        ]

    # ----- Test assertion helpers -----

    def assert_tuple_exists(self, user: str, relation: str, object: str) -> None:
        """Assert that a specific tuple exists. Raises AssertionError with details if not."""
        triple = (object, relation, user)
        if triple not in self._tuples:
            raise AssertionError(
                f'Tuple not found: ({object}, {relation}, {user})\n'
                f'Existing tuples ({len(self._tuples)}):\n'
                + '\n'.join(f'  ({o}, {r}, {u})' for o, r, u in sorted(self._tuples))
            )

    def assert_tuple_count(self, expected: int) -> None:
        """Assert the total number of stored tuples."""
        actual = len(self._tuples)
        if actual != expected:
            raise AssertionError(
                f'Expected {expected} tuples, got {actual}\n'
                f'Tuples:\n'
                + '\n'.join(f'  ({o}, {r}, {u})' for o, r, u in sorted(self._tuples))
            )

    def reset(self) -> None:
        """Clear all stored tuples."""
        self._tuples.clear()
