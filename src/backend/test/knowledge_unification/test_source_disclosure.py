"""T843: bounded, original-identity source metadata dispatch, without business I/O."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.resource_reference.application.contracts import SourceKey, SourceType
from bisheng.resource_reference.application.source_contracts import ReadIdentityFacts
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure, SourceDisclosureRuntime


def key(kind=SourceType.ASSISTANT, ident="source", tenant=101):
    return SourceKey(tenant, kind, ident, "current" if kind != SourceType.WORKFLOW_VERSION else "12")


@pytest.fixture
async def active():
    token = set_current_tenant_id(101)
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with AsyncSession(engine) as session, session.begin():
            yield session
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()


@pytest.fixture
def graph():
    identity = SimpleNamespace(acapture=AsyncMock(return_value=ReadIdentityFacts(101, "original")))
    owners = {}
    for kind in SourceType:

        async def disclose(session, *, identity, source_keys):
            return tuple(SourceDisclosure(source, "actual-name", None, None) for source in source_keys)

        owners[kind] = SimpleNamespace(adisclose_sources=AsyncMock(side_effect=disclose))
    return SourceDisclosureRuntime(owners, identity_port=identity), owners, identity


def test_immutable_closed_metadata_has_no_payload():
    item = SourceDisclosure(key(), "original-name", None, "/assistant/source/")
    assert not hasattr(item, "__dict__") and not hasattr(item, "payload_json")
    with pytest.raises(FrozenInstanceError):
        item.name = "different"


@pytest.mark.parametrize("field,value", [("source", {}), ("name", None), ("version_label", 1), ("entry", {})])
def test_metadata_rejects_untyped_values(field, value):
    values = dict(source=key(), name="original", version_label=None, entry=None)
    values[field] = value
    with pytest.raises((TypeError, ValueError)):
        SourceDisclosure(**values)


async def test_empty_batch_does_not_touch_identity_owner_or_session(graph):
    runtime, owners, identity = graph
    assert await runtime.adisclose_sources(None, identity=object(), source_keys=()) == ()
    identity.acapture.assert_not_awaited()
    assert all(owner.adisclose_sources.await_count == 0 for owner in owners.values())


@pytest.mark.parametrize("values", [[], (object(),), tuple(key(ident=str(i)) for i in range(201))])
async def test_invalid_batch_never_reaches_any_owner(active, graph, values):
    runtime, owners, _ = graph
    with pytest.raises(ReferenceCoverageNotReadyError):
        await runtime.adisclose_sources(active, identity=object(), source_keys=values)
    assert all(owner.adisclose_sources.await_count == 0 for owner in owners.values())


async def test_six_types_preserve_order_duplicates_and_hidden_positions(active, graph):
    runtime, owners, identity = graph
    values = tuple(key(kind, str(i)) for i, kind in enumerate(SourceType))
    values = (values[2], *values, values[2], key(tenant=202))
    actual = await runtime.adisclose_sources(active, identity="original", source_keys=values)
    assert len(actual) == len(values) and actual[-1] is None
    assert tuple(item.source for item in actual[:-1]) == values[:-1]
    assert actual[0] == actual[-2]
    assert identity.acapture.await_count == 2
    for kind, owner in owners.items():
        owner.adisclose_sources.assert_awaited_once()
        request = owner.adisclose_sources.call_args
        assert request.args == (active,) and request.kwargs["identity"] == "original"
        assert all(source.tenant_id == 101 and source.source_type == kind for source in request.kwargs["source_keys"])


async def test_foreign_only_is_hidden_without_any_business_call(active, graph):
    runtime, owners, _ = graph
    assert await runtime.adisclose_sources(active, identity="original", source_keys=(key(tenant=202),)) == (None,)
    assert all(owner.adisclose_sources.await_count == 0 for owner in owners.values())


async def test_real_identity_and_scope_changes_are_not_replaced_by_owner_identity(active):
    user = UserPayload(user_id=7, tenant_id=101, user_role=[])
    actor_token = set_current_permission_actor(PermissionActor(user_id=7, tenant_id=101))

    async def disclose(session, *, identity, source_keys):
        assert identity is user
        token = set_current_tenant_id(202)
        try:
            # Leave the changed context to the enclosing call; reset in cleanup.
            return (SourceDisclosure(source_keys[0], "name", None, None),)
        finally:
            session.info["scope_token"] = token

    owners = {kind: SimpleNamespace(adisclose_sources=disclose) for kind in SourceType}
    runtime = SourceDisclosureRuntime(owners)
    try:
        with pytest.raises(ReferenceCoverageNotReadyError):
            await runtime.adisclose_sources(active, identity=user, source_keys=(key(),))
    finally:
        if token := active.info.pop("scope_token", None):
            current_tenant_id.reset(token)
        reset_current_permission_actor(actor_token)


@pytest.mark.parametrize(
    "result", [[], (), (None, None), ({},), (SourceDisclosure(key(ident="wrong"), "name", None, None),)]
)
async def test_bad_or_partial_owner_result_is_not_hidden(active, graph, result):
    runtime, owners, _ = graph
    owners[SourceType.ASSISTANT].adisclose_sources.side_effect = None
    owners[SourceType.ASSISTANT].adisclose_sources.return_value = result
    with pytest.raises(ReferenceCoverageNotReadyError):
        await runtime.adisclose_sources(active, identity="original", source_keys=(key(),))


async def test_normal_hidden_result_remains_hidden(active, graph):
    runtime, owners, _ = graph
    owners[SourceType.ASSISTANT].adisclose_sources.side_effect = None
    owners[SourceType.ASSISTANT].adisclose_sources.return_value = (None,)
    assert await runtime.adisclose_sources(active, identity="original", source_keys=(key(),)) == (None,)


async def test_io_error_is_fail_closed_with_cause(active, graph):
    runtime, owners, _ = graph
    error = OSError("metadata unavailable")
    owners[SourceType.ASSISTANT].adisclose_sources.side_effect = error
    with pytest.raises(ReferenceCoverageNotReadyError) as failure:
        await runtime.adisclose_sources(active, identity="original", source_keys=(key(),))
    assert failure.value.__cause__ is error


async def test_identity_change_fails_after_successful_business_read(active, graph):
    runtime, _, identity = graph
    identity.acapture.side_effect = (ReadIdentityFacts(101, "original"), ReadIdentityFacts(101, "changed"))
    with pytest.raises(ReferenceCoverageNotReadyError):
        await runtime.adisclose_sources(active, identity="original", source_keys=(key(),))


async def test_401_sources_are_bounded_to_three_explicit_batches(active, graph):
    runtime, owners, identity = graph
    values = tuple(key(ident=str(i)) for i in range(401))
    result = []
    for start in range(0, len(values), 200):
        result.extend(
            await runtime.adisclose_sources(active, identity="original", source_keys=values[start : start + 200])
        )
    assert tuple(item.source for item in result) == values
    assert owners[SourceType.ASSISTANT].adisclose_sources.await_count == 3
    assert identity.acapture.await_count == 6


def test_composition_is_a_lazy_pure_singleton_without_bootstrap_changes(monkeypatch):
    from bisheng.resource_reference import disclosure_composition as composition

    monkeypatch.setattr(composition, "_runtime", None)
    first = composition.get_runtime()
    assert isinstance(first, SourceDisclosureRuntime) and composition.get_runtime() is first
    assert set(first.owners) == set(SourceType)
