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
    """Pure in-memory OpenFGA mock for testing.

    Updated by F004 to match the real FGAClient interface (client.py).
    Supports: write_tuples (unified), check, batch_check, list_objects,
    list_users, read_tuples, health, close.
    """

    def __init__(self) -> None:
        self._tuples: set[tuple[str, str, str]] = set()

    # ----- Write operations (unified interface matching FGAClient) -----

    async def write_tuples(
        self, writes: list[dict] = None, deletes: list[dict] = None,
    ) -> None:
        """Write and/or delete authorization tuples.

        Each item must have keys: user, relation, object.
        Matches FGAClient.write_tuples() signature.
        """
        for item in (writes or []):
            self._tuples.add((item['object'], item['relation'], item['user']))
        for item in (deletes or []):
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

    async def batch_check(self, checks: list[dict]) -> list[bool]:
        """Batch check multiple tuples. Returns list of booleans in same order."""
        return [
            (c['object'], c['relation'], c['user']) in self._tuples
            for c in checks
        ]

    async def read_tuples(
        self, user: str = None, relation: str = None, object: str = None,
    ) -> list[dict]:
        """Read tuples matching the given filter.

        Returns list of {"user": ..., "relation": ..., "object": ...}.
        """
        results = []
        for obj, rel, usr in self._tuples:
            if user and usr != user:
                continue
            if relation and rel != relation:
                continue
            if object and obj != object:
                continue
            results.append({'user': usr, 'relation': rel, 'object': obj})
        return results

    async def health(self) -> bool:
        """Always healthy in mock."""
        return True

    async def close(self) -> None:
        """No-op for mock."""
        pass

    # ----- Deprecated (kept for backward compat) -----

    async def delete_tuples(self, deletes: list[dict]) -> None:
        """Delete tuples (old interface). Prefer write_tuples(deletes=...)."""
        for item in deletes:
            self._tuples.discard((item['object'], item['relation'], item['user']))

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
