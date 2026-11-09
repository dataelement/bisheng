"""T867/T869: opaque source ordinals and real model-impact source disclosure."""

import base64
import hashlib
import json
import tracemalloc
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from bisheng.common.cursor import encode_cursor
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.logger import trace_id_var
from bisheng.llm.domain.services.model_reference_cursor import (
    ModelReferenceSourceEntry,
    ModelReferenceSourcePage,
    decode_source_cursor,
    encode_source_cursor,
    source_context,
    validate_page_size,
)
from bisheng.llm.domain.services.model_reference_service import ModelReferenceService, _binding_digest
from bisheng.resource_reference.application.contracts import SourceKey, SourceType
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure, SourceDisclosureRuntime
from test.knowledge_unification import test_llm_refs as original

model_owner_tenant = original.model_owner_tenant
removal_session = original.removal_session
impact = original.impact


def test_source_cursor_contains_only_ordinal_and_context_digest_not_names_or_keys():
    context = source_context({"identity": {"credential": "private-key"}, "command": [1, [11]], "digest": "a" * 64})
    cursor = encode_source_cursor(7, context=context)
    decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    assert decoded == {"v": 1, "s": context, "k": [7]}
    assert len(context) == 64 and "private" not in json.dumps(decoded)
    assert decode_source_cursor(cursor, context=context, candidate_count=8) == 7
    assert source_context({"b": [1], "a": True}) == source_context({"a": True, "b": [1]})


@pytest.mark.parametrize("ordinal", [-1, True, 1.0, "1", None, 9])
def test_source_cursor_rejects_invalid_or_out_of_range_ordinals(ordinal):
    with pytest.raises(ResourceReferenceInvalidError):
        decode_source_cursor(encode_cursor([ordinal], context="ctx"), context="ctx", candidate_count=9)


@pytest.mark.parametrize("cursor", [None, "", False, "not-base64", "A" * 2049])
def test_source_cursor_requires_a_bounded_canonical_continuation(cursor):
    with pytest.raises(ResourceReferenceInvalidError):
        decode_source_cursor(cursor, context="ctx", candidate_count=9)


def test_source_cursor_rejects_wrong_context_and_noncanonical_payload():
    with pytest.raises(ResourceReferenceInvalidError):
        decode_source_cursor(encode_source_cursor(1, context="old"), context="new", candidate_count=9)
    raw = json.dumps({"v": 1, "s": "ctx", "k": [1], "extra": "hidden"}).encode()
    cursor = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    with pytest.raises(ResourceReferenceInvalidError):
        decode_source_cursor(cursor, context="ctx", candidate_count=9)
    with pytest.raises(ResourceReferenceInvalidError):
        source_context({"value": float("nan")})


@pytest.mark.parametrize("size", [True, False, 0, -1, 201, 1.0, "50", None])
def test_source_page_size_does_not_coerce_invalid_input(size):
    with pytest.raises(ResourceReferenceInvalidError):
        validate_page_size(size)


def test_bounded_page_preserves_nullable_disclosure_and_actual_slot_count():
    item = ModelReferenceSourceEntry(
        SourceDisclosure(SourceKey(101, "assistant", "7", "current"), "name", None, None), 3
    )
    page = ModelReferenceSourcePage((item,), 1, True, "opaque")
    assert asdict(page)["data"][0]["matched_slot_count"] == 3
    assert item.disclosure.entry is None and item.disclosure.version_label is None
    assert validate_page_size(200) == 200


class Metadata:
    def __init__(self, *, hidden=(), failure=None):
        self.hidden, self.failure, self.calls = set(hidden), failure, []

    async def adisclose_sources(self, session, *, identity, source_keys):
        self.calls.append(source_keys)
        if self.failure:
            raise self.failure
        return tuple(
            None if key.source_id in self.hidden else SourceDisclosure(key, f"name-{key.source_id}", None, None)
            for key in source_keys
        )


def metadata(service, **kwargs):
    owner = Metadata(**kwargs)
    service.disclosure_runtime = SourceDisclosureRuntime(dict.fromkeys(SourceType, owner))
    return owner


def seed(session, *, ident="a", slots=1, tenant=101, kind="assistant", version="current"):
    _, rows = original.seed(session, tenant=tenant, source_type=kind, source_id=ident, version=version, slots=slots)
    for index, row in enumerate(rows):
        row.target_id = str(11 + index % 5)
    return rows


async def first(impact, identity, *, size=2):
    return await impact[1].ainspect_removed_models(
        impact[0], identity=identity, server_id=1, retained_model_ids=(), delete_server=True, source_page_size=size
    )


async def following(impact, identity, cursor, *, size=2):
    return await impact[1].alist_removed_model_sources(
        impact[0],
        identity=identity,
        server_id=1,
        retained_model_ids=(),
        delete_server=True,
        cursor=cursor,
        page_size=size,
    )


async def test_complete_classification_counts_distinct_sources_once_but_only_retains_first_candidate_page(impact):
    session, service, _ = impact
    owner = metadata(service, hidden={"000", "001"})
    for i in range(401):
        seed(session, ident=f"{i:03}", slots=203 if i == 2 else 1)
    seed(session, ident="foreign-secret", tenant=202)
    await session.flush()
    with original.actor() as user:
        result = await first(impact, user)
        assert dict(result.source_counts)["assistant"] == 402
        assert dict(result.qualified_counts)["assistant"] == 399
        assert dict(result.restricted_counts)["assistant"] == 3
        assert dict(result.slot_counts)["assistant"] == 604
        assert [len(call) for call in owner.calls] == [200, 200, 1]
        assert len({key for batch in owner.calls for key in batch}) == 401
        assert all(key.tenant_id == 101 for batch in owner.calls for key in batch)
        assert result.source_page.data == () and result.source_page.has_more
        assert "foreign-secret" not in json.dumps(asdict(result))
        owner.calls.clear()
        page = await following(impact, user, result.source_page.next_cursor)
        assert [item.disclosure.source.source_id for item in page.data] == ["002", "003"]
        assert [item.matched_slot_count for item in page.data] == [203, 1]
        assert [len(call) for call in owner.calls] == [2]


async def test_actual_default_owner_sql_metadata_is_used_and_missing_own_row_fails_closed(impact):
    from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig

    session, service, _ = impact
    # Exercise the production pure composition, not an alternate impact core.
    service.disclosure_runtime = None
    seed(session, ident="assistant_llm", kind="model_default")
    row = TenantSystemModelConfig(tenant_id=101, key="assistant_llm", value="not-read-secret")
    session.add(row)
    await session.flush()
    with original.actor() as user:
        result = await first(impact, user)
        item = result.source_page.data[0]
        assert (
            item.disclosure.name == "assistant_llm" and item.disclosure.entry == "/model/management?systemModel=assis"
        )
        assert dict(result.qualified_counts)["model_default"] == 1
        await session.delete(row)
        await session.flush()
        with pytest.raises(ReferenceCoverageNotReadyError):
            await first(impact, user)


@pytest.mark.parametrize("failure", [OSError("metadata unavailable"), ValueError("bad chain")])
async def test_metadata_failure_is_not_restricted_or_zero_references(impact, failure):
    session, service, _ = impact
    metadata(service, failure=failure)
    seed(session)
    await session.flush()
    with original.actor() as user, pytest.raises(ReferenceCoverageNotReadyError):
        await first(impact, user)


async def test_continuation_fresh_permissions_and_trace_change_but_no_stale_credential_or_scope(impact):
    session, service, _ = impact
    owner = metadata(service)
    for i in range(3):
        seed(session, ident=str(i))
    await session.commit()
    with original.actor() as user:
        user._runtime_credential_reference = {
            "kind": "web_session",
            "user_id": 7,
            "tenant_id": 101,
            "token_version": 1,
            "expires_at": "2030-01-01T00:00:00Z",
        }
        result = await first(impact, user)
        cursor = result.source_page.next_cursor
        trace = trace_id_var.set("a-different-request")
        try:
            owner.hidden.add("2")
            page = await following(impact, user, cursor)
            assert page.data == () and not page.has_more and page.next_cursor is None
            user._runtime_credential_reference = {**user._runtime_credential_reference, "token_version": 2}
            with pytest.raises(ResourceReferenceInvalidError):
                await following(impact, user, cursor)
        finally:
            trace_id_var.reset(trace)
    with original.actor(admin=False) as denied, pytest.raises(original.LLMModelSharedReadonlyError):
        await following(impact, denied, cursor)


async def test_original_openapi_d_user_admin_does_not_gain_a_new_web_only_credential_gate(impact):
    from bisheng.open_api.domain.context import (
        OpenApiPrincipal,
        reset_current_open_api_principal,
        set_current_open_api_principal,
    )

    session, service, _ = impact
    metadata(service)
    for i in range(3):
        seed(session, ident=str(i))
    await session.flush()
    principal = OpenApiPrincipal(
        credential_id=9,
        actor_kind="natural_person",
        actor_id=7,
        actor_name="operator",
        tenant_id=101,
        resource_owner_user_id=7,
        scopes=frozenset({"scope-b", "scope-a"}),
        mode="D",
        authorization_subject_type="user",
        authorization_subject_id=7,
        effective_user_id=7,
    )
    token = set_current_open_api_principal(principal)
    try:
        with original.actor() as user:
            assert user._runtime_credential_reference is None
            result = await first(impact, user)
            page = await following(impact, user, result.source_page.next_cursor)
            assert page.data[0].disclosure.source.source_id == "2"
            changed = set_current_open_api_principal(principal.model_copy(update={"credential_id": 10}))
            try:
                with pytest.raises(ResourceReferenceInvalidError):
                    await following(impact, user, result.source_page.next_cursor)
            finally:
                reset_current_open_api_principal(changed)
    finally:
        reset_current_open_api_principal(token)


async def test_still_admin_narrowed_scope_and_model_revision_cannot_reuse_a_source_cursor(impact):
    from bisheng.llm.domain.models.llm_server import LLMModel
    from bisheng.permission.application.data_scope import DATA_SCOPE_PERSONAL
    from bisheng.permission.application.identity import (
        PermissionActor,
        reset_current_permission_actor,
        set_current_permission_actor,
    )

    session, service, _ = impact
    metadata(service)
    for i in range(3):
        seed(session, ident=str(i))
    await session.flush()
    with original.actor() as user:
        result = await first(impact, user)
        cursor = result.source_page.next_cursor
        token = set_current_permission_actor(
            PermissionActor(
                user_id=7,
                tenant_id=101,
                tenant_admin_tenant_ids=frozenset({101}),
                data_scope=DATA_SCOPE_PERSONAL,
            )
        )
        try:
            with pytest.raises(ResourceReferenceInvalidError):
                await following(impact, user, cursor)
        finally:
            reset_current_permission_actor(token)
        retained_row = await session.get(LLMModel, 15)
        retained_row.model_name = "actual-revision-changed"
        await session.flush()
        with pytest.raises(ResourceReferenceInvalidError):
            await following(impact, user, cursor)


async def test_all_six_types_and_versions_keep_qualified_counts_and_last_page_binding_changes(impact):
    session, service, _ = impact
    metadata(service)
    for kind in SourceType:
        seed(session, ident="same", kind=kind.value)
    seed(session, ident="same", kind="workflow_version", version="history")
    last_rows = seed(session, ident="z", slots=201)
    await session.flush()
    with original.actor() as user:
        before = await first(impact, user)
        assert sum(dict(before.source_counts).values()) == 8
        assert before.qualified_counts == before.source_counts
        assert sum(dict(before.restricted_counts).values()) == 0
        last_rows[-1].slot_key = "last-page-changed"
        await session.flush()
        with pytest.raises(ResourceReferenceInvalidError):
            await following(impact, user, before.source_page.next_cursor)
        after = await first(impact, user)
        assert after.inbound_digest != before.inbound_digest and after.source_counts == before.source_counts


async def test_new_session_can_continue_but_last_binding_id_reinsertion_requires_confirmation(impact):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.resource_reference.domain.repositories.coverage_repository import CoverageRepository

    session, service, _ = impact
    metadata(service)
    for i in range(3):
        seed(session, ident=str(i))
    await session.commit()
    with original.actor() as user:
        result = await first(impact, user)
        await session.commit()
        async with AsyncSession(session.bind, expire_on_commit=False) as active:
            ledger = original.SqlLedger(active)
            service.coverage_factory = lambda _: CoverageRepository(ledger, global_port=ledger)
            page = await following((active, service, ledger), user, result.source_page.next_cursor)
            assert page.data[0].disclosure.source.source_id == "2"
            from sqlalchemy import select

            from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference

            row = (
                (await active.execute(select(BusinessResourceReference).order_by(BusinessResourceReference.id.desc())))
                .scalars()
                .first()
            )
            row.id += 500
            await active.flush()
            with pytest.raises(ResourceReferenceInvalidError):
                await following((active, service, ledger), user, result.source_page.next_cursor)
            changed = await first((active, service, ledger), user)
            assert changed.inbound_digest != result.inbound_digest


def binding(ident, *, slot="same"):
    return SimpleNamespace(
        id=ident,
        tenant_id=101,
        source_type="assistant",
        source_id="one",
        source_version="current",
        slot_key=slot,
        target_type="model",
        target_id="11",
        target_tenant_id=101,
        target_space_id=None,
        source_revision=1,
        legacy_invalid_reason=None,
        legacy_run_id=None,
        legacy_evidence_key=None,
    )


@pytest.mark.parametrize("ids", [(0,), (True,), (2**64,), (1, 1), (2, 1)])
async def test_v2_digest_rejects_invalid_or_nonmonotonic_physical_ids(impact, monkeypatch, ids):
    _, service, _ = impact
    metadata(service)

    async def pages(*args, global_id_order=False, **kwargs):
        assert global_id_order is True
        yield tuple(binding(i) for i in ids)

    monkeypatch.setattr(service.runtime.repository, "aiter_inbound_for_owner_pages", pages)
    with original.actor() as user, pytest.raises(ReferenceCoverageNotReadyError):
        await first(impact, user)


async def test_100001_slots_stream_complete_digest_without_hash_list_peak(impact, monkeypatch):
    _, service, _ = impact
    metadata(service)
    count = 100001

    async def pages(active, scope, *, global_id_order=False):
        assert global_id_order is True
        for start in range(1, count + 1, 200):
            yield tuple(binding(i, slot=str(i)) for i in range(start, min(start + 200, count + 1)))

    monkeypatch.setattr(service.runtime.repository, "aiter_inbound_for_owner_pages", pages)
    expected = hashlib.sha256(b"f118-model-inbound-v2\0")
    for i in range(1, count + 1):
        expected.update(i.to_bytes(8, "big"))
        expected.update(_binding_digest(binding(i, slot=str(i))))
    with original.actor() as user:
        tracemalloc.start()
        try:
            result = await first(impact, user)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    assert result.inbound_digest == expected.hexdigest()
    assert dict(result.slot_counts)["assistant"] == count
    assert result.source_page.data[0].matched_slot_count == count
    print(f"model-source aggregate: slots={count}, peak_bytes={peak}")
    assert peak < 1024 * 1024


def test_core_accepts_typed_disclosure_dependency_without_another_impact_runtime():
    runtime = SourceDisclosureRuntime({})
    assert ModelReferenceService(disclosure_runtime=runtime).disclosure_runtime is runtime
