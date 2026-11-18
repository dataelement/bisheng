"""Resource authorization regressions for knowledge version operations.

Synthetic repositories keep security checks deterministic without middleware.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.services import knowledge_version_service as module


@pytest.fixture
def version_case(monkeypatch, tenant_context):
    tenant_context(1)
    knowledge = SimpleNamespace(id=10, tenant_id=1, type=3, state=1)
    files = {
        key: SimpleNamespace(
            id=key,
            knowledge_id=10,
            tenant_id=1,
            status=2,
            simhash="123",
            md5=str(key),
            similar_status=1,
            file_name=f"synthetic-{key}.txt",
            file_encoding=None,
            user_name="owner",
            user_id=5,
            create_time=None,
        )
        for key in (100, 101)
    }
    docs = {
        20: SimpleNamespace(id=20, knowledge_id=10, primary_version_id=30),
        21: SimpleNamespace(id=21, knowledge_id=10, primary_version_id=31),
    }
    versions = {
        30: SimpleNamespace(id=30, document_id=20, knowledge_file_id=100, version_no=1, is_primary=False),
        31: SimpleNamespace(id=31, document_id=21, knowledge_file_id=101, version_no=1, is_primary=True),
    }
    doc_repo = MagicMock()
    doc_repo.find_by_id = AsyncMock(side_effect=lambda key: docs.get(key))
    doc_repo.find_by_knowledge_id = AsyncMock(return_value=list(docs.values()))
    version_repo = MagicMock()
    version_repo.find_by_id = AsyncMock(side_effect=lambda key: versions.get(key))
    version_repo.find_by_knowledge_file_id = AsyncMock(
        side_effect=lambda key: next((v for v in versions.values() if v.knowledge_file_id == key), None)
    )
    version_repo.find_by_document_id = AsyncMock(
        side_effect=lambda key: [v for v in versions.values() if v.document_id == key]
    )
    version_repo.find_primary = AsyncMock(return_value=None)
    version_repo.next_version_no = AsyncMock(return_value=2)
    file_repo = MagicMock()
    file_repo.find_by_id = AsyncMock(side_effect=lambda key: files.get(key))
    file_repo.find_by_ids = AsyncMock(side_effect=lambda keys: [files[k] for k in keys if k in files])
    file_repo.find_main_version_files_in_space = AsyncMock(return_value=[files[101]])
    for repo in (doc_repo, version_repo, file_repo):
        for method in ("save", "update", "delete", "update_primary_version_id"):
            setattr(repo, method, AsyncMock(return_value=SimpleNamespace(id=99)))
    monkeypatch.setattr(KnowledgeDao, "aquery_by_id", AsyncMock(return_value=knowledge))
    from bisheng.api.services import knowledge_imp
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
    from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import KnowledgeAuditTelemetryService

    monkeypatch.setattr(KnowledgeFileDao, "aget_files_by_similar_status", AsyncMock(return_value=list(files.values())))
    for name in ("delete_minio_files", "delete_vector_files"):
        monkeypatch.setattr(knowledge_imp, name, MagicMock())
    for name in (
        "audit_link_file_version",
        "audit_set_primary_version",
        "audit_delete_file_version",
        "audit_dismiss_similar_file",
    ):
        monkeypatch.setattr(KnowledgeAuditTelemetryService, name, MagicMock())
    monkeypatch.setattr(
        module,
        "bisheng_settings",
        SimpleNamespace(
            async_get_knowledge=AsyncMock(
                return_value=SimpleNamespace(
                    version_management=SimpleNamespace(enabled=True, simhash_similarity_threshold=0.85)
                )
            )
        ),
    )
    permission = AsyncMock(side_effect=HTTPException(status_code=403, detail="denied"))
    monkeypatch.setattr(module, "require_business_action", permission, raising=False)
    svc = module.KnowledgeVersionService(
        request=MagicMock(),
        login_user=SimpleNamespace(user_id=7, tenant_id=1, is_global_super=False),
        doc_repo=doc_repo,
        version_repo=version_repo,
        knowledge_file_repo=file_repo,
    )
    # Application ports own reads/transactions after these resource guards.
    svc._version_read_service = MagicMock()
    for name in (
        "list_versions_for_file",
        "search_associable_documents",
        "search_version_sources",
        "similar_candidates",
        "search_candidates_page",
    ):
        setattr(svc._version_read_service, name, AsyncMock(return_value=SimpleNamespace(knowledge_id=10)))
    svc._version_read_service.similar_candidates = AsyncMock(return_value=[])
    svc.version_mutation_application = MagicMock()
    result = SimpleNamespace(
        knowledge_id=10, file_name="synthetic", document_id=20, new_version_no=2, new_primary_version_no=1
    )
    for name in ("alink_file", "aset_primary", "amerge_document"):
        setattr(svc.version_mutation_application, name, AsyncMock(return_value=result))
    svc.deletion_application_factory = MagicMock(
        return_value=SimpleNamespace(
            adelete_historical_version=AsyncMock(
                return_value={"knowledge_id": 10, "file_name": "synthetic", "document_id": 20, "deleted_version_no": 1}
            )
        )
    )
    monkeypatch.setattr(svc, "_require_version_management_enabled", AsyncMock())
    return SimpleNamespace(
        svc=svc, files=files, docs=docs, versions=versions, knowledge=knowledge, permission=permission
    )


OPERATIONS = [
    ("list_versions_for_file", (100,)),
    ("search_associable_documents", (10, "", 100)),
    ("search_version_sources", (10, "", 100)),
    ("get_similar_candidates_for_file", (100,)),
    ("get_version_recommendations", (100,)),
    ("list_pending_similar_files", (10,)),
    ("dismiss_similar", (100,)),
    ("link_file_to_document", (100, 21)),
    ("merge_source_document_into_current", (100, 21)),
    ("set_primary_version", (30,)),
    ("delete_version", (30,)),
]


@pytest.mark.parametrize("method,args", OPERATIONS)
async def test_private_resource_denied_before_side_effects(version_case, method, args):
    case = version_case
    with pytest.raises(HTTPException) as exc:
        await getattr(case.svc, method)(*args)
    assert exc.value.status_code == 403
    case.permission.assert_awaited()
    for repo in (case.svc.doc_repo, case.svc.version_repo, case.svc.knowledge_file_repo):
        for name in ("save", "update", "delete", "update_primary_version_id"):
            getattr(repo, name).assert_not_awaited()


@pytest.mark.parametrize(
    "method,args",
    [
        ("delete_version", (30,)),
        ("set_primary_version", (30,)),
        ("list_versions_for_file", (100,)),
    ],
)
@pytest.mark.parametrize("mismatch", ["missing_file", "file_tenant", "document_knowledge", "knowledge_tenant"])
async def test_unscoped_version_cannot_escape_parent_validation(version_case, method, args, mismatch):
    case = version_case
    case.permission.side_effect = None
    if mismatch == "missing_file":
        del case.files[100]
    elif mismatch == "file_tenant":
        case.files[100].tenant_id = 2
    elif mismatch == "document_knowledge":
        case.docs[20].knowledge_id = 11
    else:
        case.knowledge.tenant_id = 2
    with pytest.raises(HTTPException) as exc:
        await getattr(case.svc, method)(*args)
    assert exc.value.status_code in (404, 409)
    for repo in (case.svc.doc_repo, case.svc.version_repo, case.svc.knowledge_file_repo):
        for name in ("save", "update", "delete", "update_primary_version_id"):
            getattr(repo, name).assert_not_awaited()


@pytest.mark.parametrize(
    "method,args",
    [
        ("search_associable_documents", (11, "", 100)),
        ("search_version_sources", (11, "", 100)),
        ("link_file_to_document", (100, 21)),
        ("merge_source_document_into_current", (100, 21)),
    ],
)
async def test_request_and_chain_knowledge_mismatch_is_rejected(version_case, method, args):
    case = version_case
    case.permission.side_effect = None
    if "search" not in method:
        case.docs[21].knowledge_id = 11
    with pytest.raises(HTTPException) as exc:
        await getattr(case.svc, method)(*args)
    assert exc.value.status_code in (404, 409)
    case.svc.version_repo.save.assert_not_awaited()
    case.svc.version_repo.delete.assert_not_awaited()


@pytest.mark.parametrize("method,args", OPERATIONS)
async def test_granted_actor_uses_actual_resource_action(version_case, method, args):
    case = version_case
    case.permission.side_effect = None
    if method == "delete_version":
        case.docs[20].primary_version_id = None
    await getattr(case.svc, method)(*args)
    calls = [call.kwargs for call in case.permission.await_args_list]
    assert calls
    writes = {
        "dismiss_similar",
        "link_file_to_document",
        "merge_source_document_into_current",
        "set_primary_version",
        "delete_version",
    }
    if method in writes:
        assert all(call == {"resource_type": "knowledge_space", "resource_id": 10, "action": "edit"} for call in calls)
    else:
        assert all(call["action"] == "visible" for call in calls)
        assert all(call["resource_id"] in {10, 100, 101} for call in calls)


async def test_default_disabled_feature_does_not_skip_read_authorization(version_case):
    version_case.svc._require_version_management_enabled.side_effect = AssertionError(
        "read must not use feature switch"
    )
    with pytest.raises(HTTPException) as exc:
        await version_case.svc.list_versions_for_file(100)
    assert exc.value.status_code == 403
    version_case.permission.assert_awaited_once_with(
        version_case.svc.login_user, resource_type="knowledge_file", resource_id=100, action="visible"
    )


@pytest.mark.parametrize(
    "method,args",
    [
        ("set_primary_version", (30,)),
        ("link_file_to_document", (100, 21)),
        ("merge_source_document_into_current", (100, 21)),
    ],
)
async def test_foreign_primary_pointer_is_rejected_before_mutation(version_case, method, args):
    case = version_case
    case.permission.side_effect = None
    case.docs[20 if method != "link_file_to_document" else 21].primary_version_id = 999
    from bisheng.common.errcode.knowledge_space import VersionLinkTargetUnavailableError

    with pytest.raises((HTTPException, VersionLinkTargetUnavailableError)):
        await getattr(case.svc, method)(*args)
    case.svc.version_repo.save.assert_not_awaited()
    case.svc.version_repo.update.assert_not_awaited()
    case.svc.doc_repo.update_primary_version_id.assert_not_awaited()


@pytest.mark.parametrize(
    "method,args", [("link_file_to_document", (100, 20)), ("merge_source_document_into_current", (100, 20))]
)
async def test_self_chain_mutations_rejected(version_case, method, args):
    case = version_case
    case.permission.side_effect = None
    with pytest.raises(HTTPException) as exc:
        await getattr(case.svc, method)(*args)
    assert exc.value.status_code == 409
    case.svc.version_repo.save.assert_not_awaited()


@pytest.mark.parametrize("knowledge_type,resource_type", [(3, "knowledge_space"), (0, "knowledge_library")])
async def test_write_action_is_routed_by_loaded_knowledge_type(version_case, knowledge_type, resource_type):
    case = version_case
    case.knowledge.type = knowledge_type
    case.permission.side_effect = None
    await case.svc.dismiss_similar(100)
    case.permission.assert_awaited_once_with(
        case.svc.login_user, resource_type=resource_type, resource_id=10, action="edit"
    )


async def test_visibility_does_not_authorize_write(version_case):
    case = version_case

    async def visible_only(user, *, resource_type, resource_id, action):
        if action != "visible":
            raise HTTPException(status_code=403)

    case.permission.side_effect = visible_only
    result = await case.svc.list_versions_for_file(100)
    assert result.knowledge_id == 10
    with pytest.raises(HTTPException) as exc:
        await case.svc.set_primary_version(30)
    assert exc.value.status_code == 403
    case.svc.version_repo.update.assert_not_awaited()


async def test_second_chain_file_is_independently_authorized(version_case):
    case = version_case
    case.versions[31].document_id = 20
    case.docs[20].primary_version_id = 31

    async def primary_only(user, *, resource_type, resource_id, action):
        if resource_type == "knowledge_file" and resource_id == 100:
            raise HTTPException(status_code=403)

    case.permission.side_effect = primary_only
    with pytest.raises(HTTPException) as exc:
        await case.svc.list_versions_for_file(101)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("method,args", [("list_versions_for_file", (100,)), ("set_primary_version", (30,))])
async def test_failed_container_does_not_allow_reads_or_mutations(version_case, method, args):
    case = version_case
    case.knowledge.state = 4
    case.permission.side_effect = None
    with pytest.raises(HTTPException) as error:
        await getattr(case.svc, method)(*args)
    assert error.value.status_code == 404
    case.svc.version_mutation_application.aset_primary.assert_not_awaited()


async def test_failed_container_cleanup_still_requires_edit(version_case):
    case = version_case
    case.knowledge.state = 4
    with pytest.raises(HTTPException) as error:
        await case.svc.delete_version(30)
    assert error.value.status_code == 403
    case.svc.deletion_application_factory.assert_not_called()


async def test_foreign_tenant_is_rejected_even_for_admin(version_case):
    case = version_case
    case.svc.login_user.is_global_super = True
    case.files[100].tenant_id = 2
    with pytest.raises(HTTPException) as exc:
        await case.svc.delete_version(30)
    assert exc.value.status_code == 404
    case.permission.assert_not_awaited()
    case.svc.version_repo.delete.assert_not_awaited()
