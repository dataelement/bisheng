"""F052 T102a — RetrievalFacadeService unit behaviour.

覆盖 AC: AC-11, AC-19, AC-21, AC-22, AC-23, AC-24, AC-27, AC-46

The facade is the only retrieval path on the open face, so the interesting
assertions are the refusals: no identity, a target that cannot be reached, a
declared knowledge base that has been deleted, a permission outage. Each of
those must produce an error rather than a smaller result set — a narrowed
answer is indistinguishable from a correct one to the caller, which is exactly
why silent narrowing is forbidden here.
"""

from unittest.mock import MagicMock

import pytest

from bisheng.common.errcode.mcp_face import (
    KnowledgeCapabilityRevokedError,
    KnowledgeUnreachableError,
    RetrievalIdentityMissingError,
    RetrievalScopeTooLargeError,
)
from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.schemas.retrieval_facade import (
    RETRIEVAL_TARGETS_MAX,
    RetrievalIdentity,
    RetrievalRequest,
)
from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL
from bisheng.permission.application.identity import (
    get_current_permission_actor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.knowledge.conftest import make_document

SPACE = KnowledgeTypeEnum.SPACE.value
LIBRARY = KnowledgeTypeEnum.NORMAL.value
QA = KnowledgeTypeEnum.QA.value
PERSONAL = KnowledgeTypeEnum.PRIVATE.value


def service_account_identity(*, subject_id: int = 7, tenant_id: int = 1) -> RetrievalIdentity:
    actor = PermissionActor(subject_type="service_account", subject_id=subject_id, tenant_id=tenant_id)
    login_user = MagicMock(user_id=subject_id, tenant_id=tenant_id, is_global_super=False)
    return RetrievalIdentity(actor=actor, login_user=login_user)


def user_identity(
    *,
    user_id: int = 11,
    tenant_id: int = 1,
    super_admin: bool = False,
    tenant_admin: bool = False,
    data_scope: str = DATA_SCOPE_ALL,
) -> RetrievalIdentity:
    actor = PermissionActor(
        subject_type="user",
        subject_id=user_id,
        tenant_id=tenant_id,
        super_admin=super_admin,
        tenant_admin_tenant_ids=frozenset({tenant_id}) if tenant_admin else frozenset(),
        data_scope=data_scope,
    )
    login_user = MagicMock(user_id=user_id, tenant_id=tenant_id, is_global_super=super_admin)
    return RetrievalIdentity(actor=actor, login_user=login_user)


# ---------------------------------------------------------------------------
# AC-23 — fail-closed on identity
# ---------------------------------------------------------------------------


async def test_identity_none_rejected_26320(fake_engine):
    with pytest.raises(RetrievalIdentityMissingError) as exc:
        await RetrievalFacadeService.retrieve(None, RetrievalRequest(query="q", knowledge_ids=[1]))
    assert exc.value.code == 26320
    assert fake_engine.instances == []


async def test_identity_without_subject_rejected_26320(fake_engine):
    identity = RetrievalIdentity(actor=None, login_user=MagicMock(user_id=1, tenant_id=1))

    with pytest.raises(RetrievalIdentityMissingError):
        await RetrievalFacadeService.retrieve(identity, RetrievalRequest(query="q", knowledge_ids=[1]))
    assert fake_engine.instances == []


# ---------------------------------------------------------------------------
# AC-22 — explicit targets, and "no targets means everything granted"
# ---------------------------------------------------------------------------


async def test_explicit_targets_all_reachable_calls_engine_with_rows(fake_engine, knowledge_rows, fake_visibility):
    knowledge_rows(1, SPACE)
    knowledge_rows(2, LIBRARY)
    fake_visibility.granted["knowledge_space"] = {1}
    fake_visibility.granted["knowledge_library"] = {2}
    fake_engine.docs_by_knowledge_default = {
        1: [make_document("from-space", document_id=10)],
        2: [make_document("from-library", document_id=20)],
    }

    result = await RetrievalFacadeService.retrieve(
        service_account_identity(), RetrievalRequest(query="q", knowledge_ids=[1, 2])
    )

    assert [chunk.content for chunk in result.chunks] == ["from-space", "from-library"]
    assert sorted(result.effective_scope) == [1, 2]
    assert result.total == 2
    assert fake_engine.instances[0].calls[0]["target_ids"] == [1, 2]


async def test_no_targets_no_whitelist_uses_all_accessible(
    fake_engine, knowledge_rows, fake_visibility, fake_visible_objects
):
    knowledge_rows(1, SPACE)
    knowledge_rows(2, LIBRARY)
    knowledge_rows(3, QA)
    fake_visible_objects.by_type["knowledge_space"] = [1, 3]
    fake_visible_objects.by_type["knowledge_library"] = [2]
    fake_visibility.granted["knowledge_space"] = {1, 3}
    fake_visibility.granted["knowledge_library"] = {2}

    result = await RetrievalFacadeService.retrieve(service_account_identity(), RetrievalRequest(query="q"))

    # QA never becomes a target, and the enumeration is asked once per type.
    assert sorted(result.effective_scope) == [1, 2]
    assert sorted(call["resource_type"] for call in fake_visible_objects.calls) == [
        "knowledge_library",
        "knowledge_space",
    ]


async def test_scope_larger_than_200_rejected_26323(fake_engine, knowledge_rows, fake_visibility, fake_visible_objects):
    fake_visible_objects.by_type["knowledge_space"] = list(range(1, 400))

    with pytest.raises(RetrievalScopeTooLargeError):
        await RetrievalFacadeService.retrieve(service_account_identity(), RetrievalRequest(query="q"))
    assert fake_engine.instances == []


async def test_too_many_explicit_targets_rejected_26323(fake_engine, knowledge_rows, fake_visibility):
    targets = list(range(1, RETRIEVAL_TARGETS_MAX + 2))

    with pytest.raises(RetrievalScopeTooLargeError):
        await RetrievalFacadeService.retrieve(
            service_account_identity(), RetrievalRequest(query="q", knowledge_ids=targets)
        )
    assert fake_engine.instances == []


async def test_admin_actor_scans_tenant_but_personal_scope_does_not(
    monkeypatch, fake_engine, knowledge_rows, fake_visibility, fake_visible_objects
):
    """design 坑 7: the admin bypass is off for a data-scope-narrowed token."""

    from bisheng.knowledge.domain.services import retrieval_facade_service as facade_mod

    scans: list[dict] = []

    async def aget_all_knowledge(name=None, knowledge_type=None, **kwargs):
        scans.append({"name": name, "type": knowledge_type, **kwargs})
        return [knowledge_rows.table[1]] if knowledge_type is KnowledgeTypeEnum.SPACE else []

    knowledge_rows(1, SPACE)
    monkeypatch.setattr(facade_mod.KnowledgeDao, "aget_all_knowledge", aget_all_knowledge)

    await RetrievalFacadeService.list_accessible_knowledge(user_identity(super_admin=True))
    assert scans, "an unnarrowed admin enumerates by tenant scan"
    assert not fake_visible_objects.calls

    scans.clear()
    fake_visible_objects.by_type["knowledge_space"] = [1]
    fake_visibility.granted["knowledge_space"] = {1}
    await RetrievalFacadeService.list_accessible_knowledge(
        user_identity(super_admin=True, data_scope=DATA_SCOPE_PERSONAL)
    )
    assert not scans, "a narrowed token must not take the admin bypass"
    assert fake_visible_objects.calls


# ---------------------------------------------------------------------------
# AC-11 / AC-27 — one answer for every kind of unreachable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("registered_type", "granted"),
    [
        (None, False),  # row does not exist
        (SPACE, False),  # exists but not granted
        (QA, True),  # unsupported type
        (PERSONAL, True),  # retired personal knowledge base
    ],
)
async def test_any_unreachable_target_fails_whole_request_26321_same_response(
    fake_engine, knowledge_rows, fake_visibility, registered_type, granted
):
    knowledge_rows(1, SPACE)
    fake_visibility.granted["knowledge_space"] = {1}
    if registered_type is not None:
        knowledge_rows(9, registered_type)
        if granted:
            fake_visibility.granted["knowledge_space"].add(9)

    with pytest.raises(KnowledgeUnreachableError) as exc:
        await RetrievalFacadeService.retrieve(
            service_account_identity(), RetrievalRequest(query="q", knowledge_ids=[1, 9])
        )

    # Only the unreachable id is named, and never *why* it is unreachable.
    assert exc.value.kwargs == {"unreachable_ids": [9]}
    assert fake_engine.instances == [] or not fake_engine.instances[0].calls


async def test_unreachable_response_is_identical_for_missing_and_ungranted(
    fake_engine, knowledge_rows, fake_visibility
):
    knowledge_rows(8, SPACE)  # exists, not granted

    with pytest.raises(KnowledgeUnreachableError) as ungranted:
        await RetrievalFacadeService.retrieve(
            service_account_identity(), RetrievalRequest(query="q", knowledge_ids=[8])
        )
    with pytest.raises(KnowledgeUnreachableError) as missing:
        await RetrievalFacadeService.retrieve(
            service_account_identity(), RetrievalRequest(query="q", knowledge_ids=[9999])
        )

    assert ungranted.value.to_dict()["status_code"] == missing.value.to_dict()["status_code"]
    assert ungranted.value.to_dict()["status_message"] == missing.value.to_dict()["status_message"]
    assert set(ungranted.value.to_dict()["data"]) == set(missing.value.to_dict()["data"])


# ---------------------------------------------------------------------------
# AC-21 / AC-46 — declared whitelist semantics
# ---------------------------------------------------------------------------


async def test_whitelist_intersects_visible_silently_when_not_targeted(fake_engine, knowledge_rows, fake_visibility):
    knowledge_rows(1, SPACE)
    knowledge_rows(2, SPACE)
    fake_visibility.granted["knowledge_space"] = {1}  # 2 is declared but invisible
    fake_engine.docs_by_knowledge_default = {1: [make_document("only-one", document_id=10)]}

    result = await RetrievalFacadeService.retrieve(user_identity(), RetrievalRequest(query="q", whitelist=[1, 2]))

    assert result.effective_scope == [1]
    assert [chunk.content for chunk in result.chunks] == ["only-one"]


async def test_whitelist_outside_target_is_unreachable(fake_engine, knowledge_rows, fake_visibility):
    """Identity never short-circuits the declared scope — not even an admin."""

    knowledge_rows(1, SPACE)
    knowledge_rows(5, SPACE)
    fake_visibility.granted["knowledge_space"] = {1, 5}

    with pytest.raises(KnowledgeUnreachableError) as exc:
        await RetrievalFacadeService.retrieve(
            user_identity(tenant_admin=True),
            RetrievalRequest(query="q", knowledge_ids=[5], whitelist=[1]),
        )
    assert exc.value.kwargs == {"unreachable_ids": [5]}


async def test_empty_whitelist_with_targets_is_unreachable(fake_engine, knowledge_rows, fake_visibility):
    knowledge_rows(1, SPACE)
    fake_visibility.granted["knowledge_space"] = {1}

    with pytest.raises(KnowledgeUnreachableError):
        await RetrievalFacadeService.retrieve(
            user_identity(), RetrievalRequest(query="q", knowledge_ids=[1], whitelist=[])
        )


async def test_empty_whitelist_without_targets_is_an_empty_result(fake_engine):
    """An app that declared nothing is F055's pre-check problem, not an error here."""

    result = await RetrievalFacadeService.retrieve(user_identity(), RetrievalRequest(query="q", whitelist=[]))

    assert result.chunks == []
    assert result.effective_scope == []
    assert fake_engine.instances == []


async def test_whitelist_entry_deleted_raises_26322_and_no_engine_call(fake_engine, knowledge_rows, fake_visibility):
    knowledge_rows(1, SPACE)
    fake_visibility.granted["knowledge_space"] = {1}

    with pytest.raises(KnowledgeCapabilityRevokedError) as exc:
        await RetrievalFacadeService.retrieve(user_identity(), RetrievalRequest(query="q", whitelist=[1, 404]))
    assert exc.value.kwargs == {"knowledge_id": 404}
    assert fake_engine.instances == [] or not fake_engine.instances[0].calls


async def test_whitelist_entry_of_unsupported_type_is_also_revoked(fake_engine, knowledge_rows, fake_visibility):
    knowledge_rows(1, SPACE)
    knowledge_rows(6, QA)
    fake_visibility.granted["knowledge_space"] = {1}

    with pytest.raises(KnowledgeCapabilityRevokedError) as exc:
        await RetrievalFacadeService.retrieve(user_identity(), RetrievalRequest(query="q", whitelist=[1, 6]))
    assert exc.value.kwargs == {"knowledge_id": 6}


async def test_same_deleted_knowledge_is_unreachable_without_a_whitelist(fake_engine, knowledge_rows, fake_visibility):
    """AC-46 second half: without declared-scope semantics it is just 26321."""

    with pytest.raises(KnowledgeUnreachableError):
        await RetrievalFacadeService.retrieve(
            service_account_identity(), RetrievalRequest(query="q", knowledge_ids=[404])
        )


# ---------------------------------------------------------------------------
# Visible clamping
# ---------------------------------------------------------------------------


async def test_top_k_and_max_content_clamped_visibly(fake_engine, knowledge_rows, fake_visibility):
    knowledge_rows(1, SPACE)
    fake_visibility.granted["knowledge_space"] = {1}
    fake_engine.docs_by_knowledge_default = {
        1: [make_document(f"c{i}", document_id=10 + i, chunk_index=i) for i in range(5)]
    }

    result = await RetrievalFacadeService.retrieve(
        service_account_identity(),
        RetrievalRequest(query="q", knowledge_ids=[1], top_k=9999, max_content=999999),
    )

    assert result.truncated_params == {"top_k": 200, "max_content": 60000}
    assert fake_engine.instances[0].calls[0]["max_content"] == 60000


async def test_within_limits_reports_no_truncation(fake_engine, knowledge_rows, fake_visibility):
    knowledge_rows(1, SPACE)
    fake_visibility.granted["knowledge_space"] = {1}

    result = await RetrievalFacadeService.retrieve(
        service_account_identity(), RetrievalRequest(query="q", knowledge_ids=[1], top_k=5)
    )

    assert result.truncated_params == {}


async def test_top_k_truncates_the_flattened_result(fake_engine, knowledge_rows, fake_visibility):
    knowledge_rows(1, SPACE)
    fake_visibility.granted["knowledge_space"] = {1}
    fake_engine.docs_by_knowledge_default = {
        1: [make_document(f"c{i}", document_id=10 + i, chunk_index=i) for i in range(5)]
    }

    result = await RetrievalFacadeService.retrieve(
        service_account_identity(), RetrievalRequest(query="q", knowledge_ids=[1], top_k=2)
    )

    assert [chunk.content for chunk in result.chunks] == ["c0", "c1"]
    assert result.total == 2


# ---------------------------------------------------------------------------
# AC-24 — a permission outage is never a smaller result
# ---------------------------------------------------------------------------


async def test_permission_unavailable_never_returns_partial(fake_engine, knowledge_rows, fake_visibility):
    knowledge_rows(1, SPACE)
    fake_visibility.granted["knowledge_space"] = {1}
    fake_engine.raises_default = PermissionServiceUnavailableError()

    with pytest.raises(PermissionServiceUnavailableError):
        await RetrievalFacadeService.retrieve(
            service_account_identity(), RetrievalRequest(query="q", knowledge_ids=[1])
        )


async def test_permission_check_failure_propagates_before_any_retrieval(monkeypatch, fake_engine, knowledge_rows):
    from bisheng.knowledge.domain.services import retrieval_facade_service as facade_mod

    knowledge_rows(1, SPACE)

    async def blow_up(*_args, **_kwargs):
        raise PermissionServiceUnavailableError()

    monkeypatch.setattr(facade_mod, "batch_check_business_actions", blow_up)

    with pytest.raises(PermissionServiceUnavailableError):
        await RetrievalFacadeService.retrieve(
            service_account_identity(), RetrievalRequest(query="q", knowledge_ids=[1])
        )
    assert fake_engine.instances == [] or not fake_engine.instances[0].calls


# ---------------------------------------------------------------------------
# AC-19 — chunk shape, actor installation, session decoupling
# ---------------------------------------------------------------------------


async def test_chunks_carry_knowledge_name_and_type(fake_engine, knowledge_rows, fake_visibility):
    knowledge_rows(1, SPACE, name="Handbook")
    fake_visibility.granted["knowledge_space"] = {1}
    fake_engine.docs_by_knowledge_default = {1: [make_document("body", document_id=10, chunk_index=3)]}

    result = await RetrievalFacadeService.retrieve(
        service_account_identity(), RetrievalRequest(query="q", knowledge_ids=[1])
    )

    chunk = result.chunks[0]
    assert (chunk.knowledge_id, chunk.knowledge_name, chunk.knowledge_type) == (1, "Handbook", SPACE)
    assert (chunk.document_id, chunk.document_name, chunk.chunk_index) == (10, "10.pdf", 3)
    assert chunk.content == "body"


async def test_facade_installs_actor_contextvar_and_resets(fake_engine, knowledge_rows, fake_visibility):
    """design 坑 5: ``resolve_permission_actor`` reads the ContextVar first."""

    knowledge_rows(1, SPACE)
    fake_visibility.granted["knowledge_space"] = {1}
    outer = PermissionActor(subject_type="user", subject_id=99, tenant_id=1)
    token = set_current_permission_actor(outer)
    identity = service_account_identity()
    try:
        await RetrievalFacadeService.retrieve(identity, RetrievalRequest(query="q", knowledge_ids=[1]))
        assert get_current_permission_actor() is outer
    finally:
        reset_current_permission_actor(token)


async def test_data_scope_personal_is_carried_into_the_permission_check(fake_engine, knowledge_rows, fake_visibility):
    knowledge_rows(1, SPACE)
    fake_visibility.granted["knowledge_space"] = {1}
    identity = user_identity(data_scope=DATA_SCOPE_PERSONAL)

    async def capture(*_args, **_kwargs):
        capture.actor = get_current_permission_actor()
        return {"1": frozenset({"visible"})}

    from bisheng.knowledge.domain.services import retrieval_facade_service as facade_mod

    original = facade_mod.batch_check_business_actions
    facade_mod.batch_check_business_actions = capture
    try:
        await RetrievalFacadeService.retrieve(identity, RetrievalRequest(query="q", knowledge_ids=[1]))
    finally:
        facade_mod.batch_check_business_actions = original

    assert capture.actor.data_scope == DATA_SCOPE_PERSONAL


def test_facade_imports_no_session_modules():
    """AC-08 / AC-19: the facade must not be able to write a chat session."""

    import ast
    from pathlib import Path

    from bisheng.knowledge.domain.services import retrieval_facade_service as facade_mod

    tree = ast.parse(Path(facade_mod.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    forbidden = ("chat_session", "models.message", "models.session", "knowledge_space_chat_service")
    offenders = [name for name in imported if any(token in name for token in forbidden)]
    assert not offenders, f"the facade must stay session-decoupled: {offenders}"


# ---------------------------------------------------------------------------
# AC-27 / AC-12 — the listing and the reachability report
# ---------------------------------------------------------------------------


async def test_list_accessible_knowledge_excludes_unsupported_types(
    fake_engine, knowledge_rows, fake_visibility, fake_visible_objects
):
    knowledge_rows(1, SPACE, name="Space one")
    knowledge_rows(2, LIBRARY, name="Library two")
    knowledge_rows(3, QA, name="QA three")
    knowledge_rows(4, PERSONAL, name="Personal four")
    fake_visible_objects.by_type["knowledge_space"] = [1, 3, 4]
    fake_visible_objects.by_type["knowledge_library"] = [2]
    fake_visibility.granted["knowledge_space"] = {1, 3, 4}
    fake_visibility.granted["knowledge_library"] = {2}

    items = await RetrievalFacadeService.list_accessible_knowledge(service_account_identity())

    assert [(item.knowledge_id, item.type) for item in items] == [(1, "space"), (2, "library")]
    assert all(item.name for item in items)


async def test_list_accessible_knowledge_filters_by_name(
    fake_engine, knowledge_rows, fake_visibility, fake_visible_objects
):
    knowledge_rows(1, SPACE, name="Employee handbook")
    knowledge_rows(2, SPACE, name="Security policy")
    fake_visible_objects.by_type["knowledge_space"] = [1, 2]
    fake_visibility.granted["knowledge_space"] = {1, 2}

    items = await RetrievalFacadeService.list_accessible_knowledge(service_account_identity(), name="handbook")

    assert [item.knowledge_id for item in items] == [1]


async def test_list_accessible_knowledge_rejects_missing_identity():
    with pytest.raises(RetrievalIdentityMissingError):
        await RetrievalFacadeService.list_accessible_knowledge(None)


async def test_check_reachable_report_three_buckets(fake_engine, knowledge_rows, fake_visibility):
    knowledge_rows(1, SPACE)
    knowledge_rows(2, SPACE)
    fake_visibility.granted["knowledge_space"] = {1}

    report = await RetrievalFacadeService.check_reachable(user_identity(), [1, 2, 404], whitelist=[1, 2, 404])

    # 1 is granted, 2 exists but is not granted, 404 was declared and is gone.
    assert report.reachable == [1]
    assert report.unreachable == [2]
    assert report.revoked == [404]
    assert fake_engine.instances == [] or not fake_engine.instances[0].calls


def test_is_supported_knowledge_type():
    assert RetrievalFacadeService.is_supported_knowledge_type(SPACE)
    assert RetrievalFacadeService.is_supported_knowledge_type(LIBRARY)
    assert not RetrievalFacadeService.is_supported_knowledge_type(QA)
    assert not RetrievalFacadeService.is_supported_knowledge_type(PERSONAL)
