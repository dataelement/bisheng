"""Request context must reach every user query without persisting membership."""

from unittest.mock import AsyncMock

import pytest

from bisheng.core.openfga.client import FGAClient
from bisheng.core.openfga.exceptions import FGAClientError
from bisheng.permission.application.department_context import ActorDepartmentContext, configure_department_context


@pytest.fixture
async def client():
    value = FGAClient("http://localhost:8080", "store", "model")
    yield value
    await value.close()


def provider():
    value = AsyncMock()
    value.load.side_effect = lambda user_id: ActorDepartmentContext(user_id, (1, 2, 3))
    return value


async def test_check_context_and_fresh_revocation(client):
    source = provider()
    configure_department_context(client, source)
    client._post = AsyncMock(return_value={"allowed": True})
    assert await client.check("user:1", "visible", "knowledge_space:A", "HIGHER_CONSISTENCY")
    body = client._post.call_args.args[1]
    assert body["tuple_key"] == {"user": "user:1", "relation": "visible", "object": "knowledge_space:A"}
    assert body["contextual_tuples"]["tuple_keys"] == [
        {"user": "user:1", "relation": "subtree_member", "object": f"department:{value}"} for value in (1, 2, 3)
    ]
    assert body["consistency"] == "HIGHER_CONSISTENCY"
    source.load.side_effect = lambda user_id: ActorDepartmentContext(user_id, ())
    await client.check("user:1", "visible", "knowledge_space:A")
    assert "contextual_tuples" not in client._post.call_args.args[1]
    assert source.load.await_count == 2


async def test_batch_shares_input_across_fifty_item_chunks_and_isolates_users(client):
    source = provider()
    configure_department_context(client, source)

    async def post(_, body):
        return {"result": {item["correlation_id"]: {"allowed": True} for item in body["checks"]}}

    client._post = AsyncMock(side_effect=post)
    checks = [{"user": f"user:{n % 2 + 1}", "relation": "visible", "object": f"knowledge_space:{n}"} for n in range(60)]
    assert await client.batch_check(checks) == [True] * 60
    assert source.load.await_count == 2
    assert client._post.await_count == 2
    for call in client._post.call_args_list:
        for item in call.args[1]["checks"]:
            assert {key["user"] for key in item["contextual_tuples"]["tuple_keys"]} == {item["tuple_key"]["user"]}


async def test_lists_and_special_subjects(client):
    source = provider()
    configure_department_context(client, source)
    client._post = AsyncMock(return_value={"objects": ["knowledge_space:A"]})
    assert await client.list_objects("user:1", "visible", "knowledge_space") == ["knowledge_space:A"]
    assert len(client._post.call_args.args[1]["contextual_tuples"]["tuple_keys"]) == 3

    async def stream(_, body):
        assert len(body["contextual_tuples"]["tuple_keys"]) == 3
        yield {"result": {"object": "knowledge_space:A"}}

    client._streamed_post = stream
    assert await client.stream_list_objects("user:1", "visible", "knowledge_space") == ("knowledge_space:A",)
    await client.check("department:1#subtree_member", "visible", "knowledge_space:A")
    assert "contextual_tuples" not in client._post.call_args.args[1]
    assert source.load.await_count == 2


async def test_missing_provider_failure_and_overflow_never_send_partial_request(client):
    client.require_contextual_provider = True
    client._post = AsyncMock()
    with pytest.raises(FGAClientError):
        await client.check("user:1", "visible", "knowledge_space:A")
    source = provider()
    source.load.side_effect = RuntimeError("organization unavailable")
    configure_department_context(client, source)
    with pytest.raises(RuntimeError, match="organization unavailable"):
        await client.check("user:1", "visible", "knowledge_space:A")
    source.load.side_effect = lambda uid: ActorDepartmentContext(uid, tuple(range(1, 102)))
    with pytest.raises(FGAClientError, match="limit"):
        await client.check("user:1", "visible", "knowledge_space:A")
    client._post.assert_not_awaited()


async def test_transient_relation_cannot_be_persisted(client):
    configure_department_context(client, provider())
    client._post = AsyncMock()
    with pytest.raises(FGAClientError):
        await client.write_tuples(writes=[{"user": "user:1", "relation": "subtree_member", "object": "department:1"}])
    client._post.assert_not_awaited()


async def test_unrelated_identity_relations_do_not_load_organization(client):
    source = provider()
    source.load.side_effect = RuntimeError("organization unavailable")
    configure_department_context(client, source)
    client._post = AsyncMock(return_value={"allowed": True, "objects": []})
    for object_type, relation in (
        ("system", "super_admin"),
        ("tenant", "member"),
        ("department", "admin"),
        ("department", "member"),
        ("user_group", "member"),
    ):
        assert await client.check("user:1", relation, f"{object_type}:1")
        assert "contextual_tuples" not in client._post.call_args.args[1]
        assert await client.list_objects("user:1", relation, object_type) == []
    source.load.assert_not_awaited()
    with pytest.raises(RuntimeError, match="organization unavailable"):
        await client.check("user:1", "manager", "llm_server:1")


async def test_nested_operations_reuse_only_until_scope_closes(client):
    from bisheng.core.openfga.contextual import contextual_tuple_scope

    source = provider()
    configure_department_context(client, source)
    client._post = AsyncMock(return_value={"allowed": True})
    with contextual_tuple_scope():
        await client.check("user:1", "visible", "knowledge_space:1")
        with contextual_tuple_scope():
            await client.check("user:1", "can_edit", "knowledge_file:1")
    assert source.load.await_count == 1
    await client.check("user:1", "visible", "knowledge_space:1")
    assert source.load.await_count == 2


async def test_contextual_legacy_results_never_use_persistent_cache(client, monkeypatch):
    from bisheng.permission.domain.services.permission_cache import PermissionCache
    from bisheng.permission.domain.services.permission_service import PermissionService

    configure_department_context(client, provider())
    client._post = AsyncMock(return_value={"allowed": False, "objects": []})
    monkeypatch.setattr(PermissionService, "_aget_fga", AsyncMock(return_value=client))
    for name in ("get_check", "set_check", "get_list_objects", "set_list_objects"):
        monkeypatch.setattr(PermissionCache, name, AsyncMock(side_effect=AssertionError("stale cache used")))
    assert not await PermissionService.check(1, "manager", "llm_server", "1")
    assert await PermissionService.list_accessible_ids(1, "manager", "llm_server") == []
    for name in ("get_check", "set_check", "get_list_objects", "set_list_objects"):
        getattr(PermissionCache, name).assert_not_awaited()
    assert client._post.await_count == 2


async def test_invalid_principal_never_reaches_openfga(client):
    source = provider()
    configure_department_context(client, source)
    client._post = AsyncMock()
    for user in ("user:01", "user:-1", "user:0", "user:abc"):
        with pytest.raises(FGAClientError, match="Invalid"):
            await client.check(user, "visible", "knowledge_space:1")
    source.load.assert_not_awaited()
    client._post.assert_not_awaited()
