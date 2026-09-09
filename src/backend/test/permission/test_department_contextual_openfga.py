"""Real, unmodified OpenFGA HTTP integration; owns one disposable Store.

Run with FGA_CONTEXTUAL_TEST_URL pointing at an isolated test instance.
AC-01/02: direct and inherited membership keep distinct meanings.
AC-03/04: complete F048 gates and batch/list APIs preserve decisions.
AC-05: fresh context observes revocation without persistent closure writes.
"""

from __future__ import annotations

import copy
import os
import statistics
from time import perf_counter
from unittest.mock import AsyncMock

import httpx
import pytest

from bisheng.core.openfga.authorization_model_f048 import build_authorization_model_f048
from bisheng.core.openfga.client import FGAClient
from bisheng.database.models.department import Department, UserDepartment
from bisheng.department.domain.services.permission_context import DepartmentPermissionContextProvider
from bisheng.permission.application.department_context import configure_department_context
from test.department import test_permission_context as organization_tests
from test.permission.test_f048_authorization_model import _active_model_tuples, _resource_grant_tuples

database = organization_tests.database

pytestmark = pytest.mark.skipif(
    not os.environ.get("FGA_CONTEXTUAL_TEST_URL"), reason="requires isolated OpenFGA HTTP instance"
)


@pytest.fixture
async def runtime():
    url = os.environ["FGA_CONTEXTUAL_TEST_URL"]
    async with httpx.AsyncClient(base_url=url, timeout=60) as http:
        response = await http.post("/stores", json={"name": "e2e-contextual-departments"})
        response.raise_for_status()
        store = response.json()["id"]
        bootstrap = FGAClient(url, store, "bootstrap", timeout=60)
        clients = [bootstrap]
        try:
            model = build_authorization_model_f048()
            old = copy.deepcopy(model)
            department = next(item for item in old["type_definitions"] if item["type"] == "department")
            department["relations"]["subtree_member"] = {
                "union": {
                    "child": [
                        {"computedUserset": {"relation": "member"}},
                        {
                            "tupleToUserset": {
                                "tupleset": {"relation": "child"},
                                "computedUserset": {"relation": "subtree_member"},
                            }
                        },
                    ]
                }
            }
            del department["metadata"]["relations"]["subtree_member"]
            legacy = bootstrap.for_model(await bootstrap.write_authorization_model(old))
            client = bootstrap.for_model(await bootstrap.write_authorization_model(model))
            clients.extend([legacy, client])
            yield client, legacy
        finally:
            for client in clients:
                await client.close()
            response = await http.delete(f"/stores/{store}")
            assert response.status_code in (200, 204)
            assert (await http.get(f"/stores/{store}")).status_code == 404


async def test_full_model_large_department_batches_lists_and_revocation(runtime, database):
    """AC-01..05: compare real F048 decisions on a 4681-department tree."""
    client, legacy = runtime
    keys = _active_model_tuples(actions=("download", "edit", "delete", "manage_permission"), grant_levels=(1,))
    frontier = [1]
    parent = {}
    node = 1
    for _ in range(4):
        following = []
        for root in frontier:
            for _ in range(8):
                node += 1
                following.append(node)
                parent[node] = root
                keys.add((f"department:{node}", "child", f"department:{root}"))
        frontier = following
    leaf = frontier[-1]
    ancestors = [leaf]
    while ancestors[-1] in parent:
        ancestors.append(parent[ancestors[-1]])
    keys.add(("user:1", "member", f"department:{leaf}"))
    keys.add(("user:2", "member", "department:99999"))
    for n in range(10):
        keys |= _resource_grant_tuples(
            resource=f"knowledge_file:f{n}",
            grant=f"permission_grant:g{n}",
            model_key="editor",
            subject="department:1#subtree_member",
        )
    for n in range(60):
        keys.add(("department:1#subtree_member", "visible", f"knowledge_space:s{n}"))
    keys.add(("department:1#member", "visible", "channel:direct-only"))
    writes = [{"user": u, "relation": r, "object": o} for u, r, o in sorted(keys)]
    for offset in range(0, len(writes), 90):
        await client.write_tuples(writes=writes[offset : offset + 90])
    _, sessions = database
    async with sessions() as session:
        session.add_all(
            [
                Department(
                    id=value, dept_id=f"e2e-context-{value}", name="fixture", tenant_id=1, parent_id=parent.get(value)
                )
                for value in range(1, node + 1)
            ]
        )
        session.add(Department(id=99999, dept_id="e2e-context-outside", name="outside", tenant_id=1))
        session.add_all(
            [UserDepartment(id=1, user_id=1, department_id=leaf), UserDepartment(id=2, user_id=2, department_id=99999)]
        )
        await session.commit()
    source = DepartmentPermissionContextProvider()
    source.load = AsyncMock(wraps=source.load)
    configure_department_context(client, source)
    for action in ("download", "edit"):
        for user, expected in (("user:1", True), ("user:2", False)):
            checks = [{"user": user, "relation": f"can_{action}", "object": f"knowledge_file:f{n}"} for n in range(10)]
            start = perf_counter()
            before = await legacy.batch_check(checks, "HIGHER_CONSISTENCY")
            legacy_ms = (perf_counter() - start) * 1000
            start = perf_counter()
            after = await client.batch_check(checks, "HIGHER_CONSISTENCY")
            optimized_ms = (perf_counter() - start) * 1000
            assert before == after == [expected] * 10
            print(f"{action}/{user}: legacy_ms={legacy_ms:.2f} contextual_ms={optimized_ms:.2f}")
    assert not await client.check("user:1", "visible", "channel:direct-only")
    for action in ("delete", "manage_permission", "grant_level_1"):
        assert await client.check("user:1", f"can_{action}", "knowledge_file:f0")
        assert not await client.check("user:2", f"can_{action}", "knowledge_file:f0")
    checks = [{"user": "user:1", "relation": "visible", "object": f"knowledge_space:s{n}"} for n in range(60)]
    durations = []
    for _ in range(30):
        source.load.reset_mock()
        start = perf_counter()
        assert await client.batch_check(checks, "HIGHER_CONSISTENCY") == [True] * 60
        durations.append((perf_counter() - start) * 1000)
        assert source.load.await_count == 1
    print(f"sixty_spaces: rounds=30 median_ms={statistics.median(durations):.2f} p95_ms={sorted(durations)[28]:.2f}")
    expected = {f"knowledge_space:s{n}" for n in range(60)}
    assert set(await client.list_objects("user:1", "visible", "knowledge_space", "HIGHER_CONSISTENCY")) == expected
    assert (
        set(await client.stream_list_objects("user:1", "visible", "knowledge_space", "HIGHER_CONSISTENCY")) == expected
    )
    assert await client.list_objects("user:2", "visible", "knowledge_space", "HIGHER_CONSISTENCY") == []
    # New requests see revoked organization facts even without a persistent
    # ancestor-member deletion in FGA; direct member remains a distinct relation.
    async with sessions() as session:
        await session.delete(await session.get(UserDepartment, 1))
        await session.commit()
    assert not await client.check("user:1", "can_edit", "knowledge_file:f0", "HIGHER_CONSISTENCY")
    # Restore membership and remove a resource gate: context must not bypass it.
    async with sessions() as session:
        session.add(UserDepartment(id=1, user_id=1, department_id=leaf))
        await session.commit()
    await client.write_tuples(
        deletes=[{"user": "user:*", "relation": "permission_enabled", "object": "knowledge_file:f0"}]
    )
    assert not await client.check("user:1", "can_edit", "knowledge_file:f0", "HIGHER_CONSISTENCY")
    assert await client.read_tuples(user="user:1", relation="subtree_member", object="department:") == []


async def test_forty_level_department_does_not_consume_fga_resolution_depth(runtime, database):
    """AC-06: 40 departments become flat request inputs with real SQL reads."""
    from bisheng.core.openfga.exceptions import FGAClientError

    client, legacy = runtime
    _, sessions = database
    async with sessions() as session:
        session.add_all(
            [
                Department(id=n, dept_id=f"deep-{n}", name="fixture", tenant_id=1, parent_id=n - 1 if n > 1 else None)
                for n in range(1, 41)
            ]
        )
        session.add(UserDepartment(id=1, user_id=1, department_id=40))
        await session.commit()
    keys = _active_model_tuples(actions=("edit",)) | _resource_grant_tuples(
        resource="knowledge_file:deep",
        grant="permission_grant:deep",
        model_key="editor",
        subject="department:1#subtree_member",
    )
    keys.add(("user:1", "member", "department:40"))
    keys |= {(f"department:{n}", "child", f"department:{n - 1}") for n in range(2, 41)}
    writes = [{"user": u, "relation": r, "object": o} for u, r, o in sorted(keys)]
    for offset in range(0, len(writes), 90):
        await client.write_tuples(writes=writes[offset : offset + 90])
    with pytest.raises(FGAClientError, match="authorization_model_resolution_too_complex"):
        await legacy.check("user:1", "can_edit", "knowledge_file:deep", "HIGHER_CONSISTENCY")
    configure_department_context(client, DepartmentPermissionContextProvider())
    assert await client.check("user:1", "can_edit", "knowledge_file:deep", "HIGHER_CONSISTENCY")
    assert not await client.check("user:1", "member", "department:1", "HIGHER_CONSISTENCY")
