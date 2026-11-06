"""Version history and candidates use real loaded-row F048 targets."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import KnowledgeSpaceInvalidCursorError, SpaceFileNotFoundError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import management_tenant_scope, tenant_execution_scope
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    F048KnowledgeFilePermissionAdapter,
    KnowledgeFileDaoPermissionLoader,
)
from bisheng.knowledge.domain.services.knowledge_version_read_service import KnowledgeVersionReadService
from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)
from bisheng.permission.application import business_authorization
from bisheng.permission.application.control_state import PermissionResourceSnapshot
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.knowledge_unification import test_kn_version_read_repository as native

catalog = native.catalog
concrete_tenant = native.concrete_tenant
chain, space = native.chain, native.space


@pytest.fixture
def identity():
    actor = PermissionActor(user_id=7, current_tenant_id=101)
    token = set_current_permission_actor(actor)
    try:
        yield actor
    finally:
        reset_current_permission_actor(token)


@pytest.fixture
async def reads(catalog, identity, monkeypatch):
    facts = SimpleNamespace(allowed=set(), missing=set(), checked=[], snapshots=[], actors=[], modes={})

    async def snapshots(keys):
        assert catalog.facts.open_sessions == 0
        facts.snapshots.append(keys)
        return {
            key: PermissionResourceSnapshot(
                *key, 3, "ctx3", facts.modes.get(int(key[2]), "CUSTOM"), None, None, "READY"
            )
            for key in keys
            if int(key[2]) not in facts.missing
        }

    async def check(actor, targets, action):
        assert catalog.facts.open_sessions == 0 and action == "visible"
        facts.actors.append(actor)
        ids = tuple(int(target.resource_id) for target in targets)
        facts.checked.append(ids)
        assert all(target.tenant_id == 101 and target.resource_type == "knowledge_file" for target in targets)
        return tuple(ident in facts.allowed for ident in ids)

    runtime = SimpleNamespace(batch_check_actions=AsyncMock(side_effect=check))
    monkeypatch.setattr(business_authorization, "get_f048_runtime", AsyncMock(return_value=runtime))
    adapter = F048KnowledgeFilePermissionAdapter(
        loader=KnowledgeFileDaoPermissionLoader(
            SimpleNamespace(get_permission_snapshots=AsyncMock(side_effect=snapshots))
        ),
        permission=SimpleNamespace(),
    )
    user = UserPayload(user_id=7, tenant_id=101, user_role=[])
    service = KnowledgeVersionReadService(
        Request({"type": "http", "headers": []}), user, repository=catalog.repository, permission_adapter=adapter
    )
    return SimpleNamespace(
        service=service, adapter=adapter, user=user, facts=facts, catalog=catalog, runtime=runtime, actor=identity
    )


async def test_requested_file_visible_is_the_only_read_action_and_hidden_primary_cannot_leak(reads):
    await reads.catalog.seed([space(), *chain(1, 3)])
    reads.facts.allowed.update({10001, 10002})
    reads.facts.modes[10001] = "INHERIT"
    result = await reads.service.list_versions_for_file(10001)
    assert result.title == "file 1 v1.md" and result.current_primary_version_no is None
    assert result.doc_code is None and [row.version_no for row in result.versions] == [1, 2]
    assert "owner 10003" not in result.model_dump_json() and "v3.md" not in result.model_dump_json()
    assert all(key[1] == "knowledge_file" for batch in reads.facts.snapshots for key in batch)
    assert reads.facts.actors and all(actor is reads.actor for actor in reads.facts.actors)


async def test_visible_primary_supplies_header_while_history_keeps_failed_processing_versions(reads):
    await reads.catalog.seed([space(), *chain(1, 3)])
    await reads.catalog.change(KnowledgeFile, 10001, status=3, file_encoding="historical-code")
    await reads.catalog.change(KnowledgeFile, 10002, status=4)
    await reads.catalog.change(KnowledgeFile, 10003, file_encoding="current-code")
    reads.facts.allowed.update({10001, 10002, 10003})
    result = await reads.service.list_versions_for_file(10001)
    assert result.title == "file 1 v3.md" and result.doc_code == "current-code"
    assert result.current_primary_version_no == 3
    assert [entry.status for entry in result.versions] == [3, 4, 2]


async def test_hidden_requested_file_is_not_authorized_by_visible_siblings(reads):
    await reads.catalog.seed([space(), *chain(1, 2)])
    reads.facts.allowed.add(10002)
    with pytest.raises(PermissionDeniedError):
        await reads.service.list_versions_for_file(10001)


async def test_missing_permission_snapshot_never_becomes_a_visible_historical_version(reads):
    await reads.catalog.seed([space(), *chain(1, 2)])
    reads.facts.allowed.update({10001, 10002})
    reads.facts.missing.add(10002)
    result = await reads.service.list_versions_for_file(10001)
    assert [row.knowledge_file_id for row in result.versions] == [10001]
    assert result.current_primary_version_no is None


async def test_foreign_or_corrupt_hidden_history_still_fails_the_complete_chain(reads):
    await reads.catalog.seed([space(), *chain(1, 2)])
    await reads.catalog.change(KnowledgeFile, 10002, tenant_id=202)
    reads.facts.allowed.add(10001)
    with pytest.raises(SpaceFileNotFoundError):
        await reads.service.list_versions_for_file(10001)


async def test_candidates_keep_literal_matching_self_exclusion_success_and_singleton_rules(reads):
    await reads.catalog.seed([space(), *chain(1), *chain(2), *chain(3, 2), *chain(4), *chain(5)])
    await reads.catalog.change(KnowledgeFile, 20001, file_name="literal%_/ space.md")
    await reads.catalog.change(KnowledgeFile, 30002, file_name="literal%_/ version.md")
    await reads.catalog.change(KnowledgeFile, 40001, file_name="literal%_/ hidden.md")
    await reads.catalog.change(KnowledgeFile, 50001, file_name="literal%_/ failed.md", status=3)
    reads.facts.allowed.update({10001, 20001, 30002, 50001})
    all_targets = await reads.service.search_associable_documents(10, "  LITERAL%_/  ", 10001)
    singleton = await reads.service.search_version_sources(10, "literal%_/", 10001)
    assert [entry.document_id for entry in all_targets] == [2, 3]
    assert [entry.document_id for entry in singleton] == [2]
    assert await reads.service.search_associable_documents(10, "literal___", 10001) == []


async def test_cursor_pages_resume_after_consumed_not_prechecked_batch_rows(reads):
    await reads.catalog.seed([space(), *[row for ident in range(1, 9) for row in chain(ident)]])
    reads.facts.allowed.update({10001, 20001, 40001, 60001, 80001})
    values, cursor = [], None
    while True:
        result = await reads.service.search_candidates_page(
            knowledge_id=10, keyword="", current_file_id=10001, page_size=1, cursor=cursor
        )
        values.extend(entry.document_id for entry in result.data)
        if not result.has_more:
            assert result.next_cursor is None
            break
        assert result.next_cursor != cursor
        cursor = result.next_cursor
    assert values == [2, 4, 6, 8]


async def test_empty_budget_page_advances_and_legacy_array_remains_complete_beyond_1000(reads):
    await reads.catalog.seed([space(), *[row for ident in range(1, 1203) for row in chain(ident)]])
    reads.facts.allowed.update({10001, 12020001})
    first = await reads.service.search_candidates_page(knowledge_id=10, keyword="", current_file_id=10001, page_size=40)
    assert first.data == [] and first.has_more and first.next_cursor
    second = await reads.service.search_candidates_page(
        knowledge_id=10, keyword="", current_file_id=10001, page_size=40, cursor=first.next_cursor
    )
    assert [row.document_id for row in second.data] == [1202] and not second.has_more
    all_results = await reads.service.search_associable_documents(10, "", 10001)
    assert [entry.document_id for entry in all_results] == [1202]
    assert max(map(len, reads.facts.checked)) <= 100


@pytest.mark.parametrize("changed", ["keyword", "file", "mode", "actor", "data_scope", "management", "credential"])
async def test_cursor_rejects_context_changes_without_becoming_an_authority(reads, changed):
    await reads.catalog.seed([space(), *chain(1), *chain(2), *chain(3)])
    reads.facts.allowed.update({10001, 20001, 30001})
    options = {"knowledge_id": 10, "keyword": "", "current_file_id": 10001, "page_size": 1}
    first = await reads.service.search_candidates_page(**options)
    assert first.next_cursor
    token = principal_token = None
    if changed == "keyword":
        options["keyword"] = "other"
    elif changed == "file":
        options["current_file_id"] = 20001
    elif changed == "mode":
        options["source_only"] = True
    elif changed == "actor":
        token = set_current_permission_actor(PermissionActor(user_id=8, current_tenant_id=101))
    elif changed == "data_scope":
        token = set_current_permission_actor(replace(reads.actor, data_scope="personal_only"))
    elif changed == "credential":
        principal_token = set_current_open_api_principal(
            OpenApiPrincipal(
                credential_id=9,
                actor_kind="natural_person",
                actor_id=7,
                actor_name="user",
                tenant_id=101,
                resource_owner_user_id=7,
                scopes=frozenset({"filelib:read"}),
                authorization_subject_type="user",
                authorization_subject_id=7,
                effective_user_id=7,
            )
        )
    try:
        if changed == "management":
            with management_tenant_scope(101), pytest.raises(KnowledgeSpaceInvalidCursorError):
                await reads.service.search_candidates_page(**options, cursor=first.next_cursor)
        else:
            with pytest.raises(KnowledgeSpaceInvalidCursorError):
                await reads.service.search_candidates_page(**options, cursor=first.next_cursor)
    finally:
        if token is not None:
            reset_current_permission_actor(token)
        if principal_token is not None:
            reset_current_open_api_principal(principal_token)


@pytest.mark.parametrize("cursor", ["malformed", "e30", "null", "[]"])
async def test_bad_cursor_is_a_business_error(reads, cursor):
    await reads.catalog.seed([space(), *chain(1)])
    reads.facts.allowed.add(10001)
    with pytest.raises(KnowledgeSpaceInvalidCursorError):
        await reads.service.search_candidates_page(knowledge_id=10, keyword="", current_file_id=10001, cursor=cursor)


async def test_cross_space_anchor_is_rejected_before_candidate_scan(reads, monkeypatch):
    await reads.catalog.seed([space(), *chain(1)])
    reads.facts.allowed.add(10001)
    scan = AsyncMock(side_effect=AssertionError("foreign scope must not scan"))
    monkeypatch.setattr(reads.catalog.repository, "alist_candidates", scan)
    with pytest.raises(SpaceFileNotFoundError):
        await reads.service.search_associable_documents(20, "", 10001)
    scan.assert_not_awaited()


@pytest.mark.parametrize(
    "actor",
    [
        PermissionActor(subject_type="service_account", subject_id=9, tenant_id=101),
        PermissionActor(user_id=7, current_tenant_id=101, data_scope="personal_only"),
    ],
)
async def test_original_service_account_and_narrowed_actor_are_passed_unchanged(reads, actor):
    await reads.catalog.seed([space(), *chain(1)])
    reads.facts.allowed.add(10001)
    token = set_current_permission_actor(actor)
    try:
        result = await reads.service.list_versions_for_file(10001)
        assert len(result.versions) == 1
        assert all(value is actor for value in reads.facts.actors)
    finally:
        reset_current_permission_actor(token)


async def test_home_identity_is_not_changed_for_trusted_management_super_and_only_loaded_targets_shortcut(reads):
    await reads.catalog.seed([space(), *chain(1, 3)])
    reads.facts.missing.add(10002)
    await reads.catalog.change(KnowledgeFile, 10003, status=999)
    original = UserPayload(user_id=7, tenant_id=1, user_role=[], is_global_super=True)
    service = KnowledgeVersionReadService(
        None, original, repository=reads.catalog.repository, permission_adapter=reads.adapter
    )
    token = set_current_permission_actor(None)
    try:
        with management_tenant_scope(101):
            result = await service.list_versions_for_file(10001)
        assert [item.knowledge_file_id for item in result.versions] == [10001]
        assert original.tenant_id == 1
        reads.runtime.batch_check_actions.assert_not_awaited()
    finally:
        reset_current_permission_actor(token)


@pytest.mark.parametrize("context", ["no_pin", "wrong_subject", "narrowed"])
async def test_untrusted_or_narrowed_cross_home_super_is_denied_before_sql(reads, context):
    original = UserPayload(user_id=7, tenant_id=1, user_role=[], is_global_super=True)
    actor = PermissionActor(
        user_id=8 if context == "wrong_subject" else 7,
        current_tenant_id=1,
        super_admin=True,
        data_scope="personal_only" if context == "narrowed" else "all_visible",
    )
    token = set_current_permission_actor(actor)
    service = KnowledgeVersionReadService(
        None, original, repository=reads.catalog.repository, permission_adapter=reads.adapter
    )
    scope = tenant_execution_scope(101) if context == "no_pin" else management_tenant_scope(101)
    try:
        with scope, pytest.raises(PermissionDeniedError):
            await service.list_versions_for_file(10001)
        assert reads.catalog.facts.sql == []
    finally:
        reset_current_permission_actor(token)


async def test_old_service_three_reads_delegate_without_touching_original_writes(reads):
    await reads.catalog.seed([space(), *chain(1), *chain(2)])
    reads.facts.allowed.update({10001, 20001})
    service = KnowledgeVersionService(None, reads.user, None, None, None, version_read_service=reads.service)
    assert (await service.list_versions_for_file(10001)).document_id == 1
    assert [entry.document_id for entry in await service.search_associable_documents(10, "", 10001)] == [2]
    assert [entry.document_id for entry in await service.search_version_sources(10, "", 10001)] == [2]


async def test_old_history_service_preserves_the_original_missing_chain_http_404(reads):
    from fastapi import HTTPException

    service = KnowledgeVersionService(None, reads.user, None, None, None, version_read_service=reads.service)
    with pytest.raises(HTTPException) as failure:
        await service.list_versions_for_file(999)
    assert failure.value.status_code == 404
