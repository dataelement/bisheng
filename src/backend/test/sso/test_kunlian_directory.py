"""T009 覆盖 AC-06, AC-16, AC-19, AC-26。SQLite 不证明生产行锁。"""

from contextlib import asynccontextmanager
from datetime import datetime
from importlib import import_module

import pytest
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.sso_sync import KunlianSyncConflictError
from bisheng.core.context.tenant import current_tenant_id
from bisheng.sso_sync.domain.models.kunlian import KunlianConnectionState, KunlianSyncBatch
from test.sso.kunlian_fakes import FrozenClock


@pytest.fixture
async def directory_store(async_db_engine):
    tables = [t for t in SQLModel.metadata.sorted_tables if t.name.startswith("kunlian_")]
    async with async_db_engine.begin() as conn:
        await conn.run_sync(lambda sync: SQLModel.metadata.create_all(sync, tables=tables))

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(async_db_engine, expire_on_commit=False) as session:
            yield session

    async with sessions() as session:
        session.add(KunlianConnectionState(connection_id="fixture", active_batch_id="previous-good"))
        await session.commit()
    token = current_tenant_id.set(1)
    clock = FrozenClock(datetime(2026, 11, 3))
    try:
        try:
            module = import_module("bisheng.sso_sync.domain.repositories.kunlian")
        except ModuleNotFoundError as exc:
            if exc.name not in ("bisheng.sso_sync.domain.repositories", "bisheng.sso_sync.domain.repositories.kunlian"):
                raise
            pytest.fail("T010 repository is not implemented", pytrace=False)
        yield module.KunlianDirectoryRepository(sessions, clock=clock), sessions, clock, module
    finally:
        current_tenant_id.reset(token)


async def test_merge_exclusion_renewal_and_expired_worker(directory_store):
    repo, sessions, clock, module = directory_store
    assert await repo.request_sync("fixture") == 1
    assert await repo.request_sync("fixture") == 2
    first = await repo.claim_or_renew_lease("fixture", "a", key_version="key-v1", page_size=20)
    other = module.KunlianDirectoryRepository(sessions, clock=clock)
    assert await other.claim_or_renew_lease("fixture", "b", key_version="key-v1", page_size=20) is None
    assert await repo.claim_or_renew_lease("fixture", "a", key_version="key-v1", page_size=20, lease=first) == first
    clock.advance(61)
    second = await other.claim_or_renew_lease("fixture", "b", key_version="key-v1", page_size=20)
    assert second.fence > first.fence and second.batch_id != first.batch_id
    with pytest.raises(KunlianSyncConflictError):
        await repo.mark_failed(first, "UPSTREAM_UNAVAILABLE")
    async with sessions() as session:
        old = await session.get(KunlianSyncBatch, first.batch_id)
        state = await session.get(KunlianConnectionState, "fixture")
        assert old.status == "ABANDONED"
        assert state.active_batch_id == "previous-good" and state.sync_completed_version == 0
        assert state.sync_requested_version == 2


@pytest.mark.parametrize("changed", ["key", "page_size", "cursor"])
async def test_resume_parameters_and_failed_batch_preserve_previous_directory(directory_store, changed):
    repo, sessions, _, _ = directory_store
    lease = await repo.claim_or_renew_lease("fixture", "worker", key_version="key-v1", page_size=20)
    await repo.stage_page(lease, tenants=[], members=[], next_cursor_ciphertext="ciphertext-page-2")
    kwargs = {
        "tenants": [],
        "members": [],
        "expected_cursor_ciphertext": "ciphertext-page-2",
        "next_cursor_ciphertext": None,
    }
    kwargs.update(
        {
            "key": {"key_version": "key-v2"},
            "page_size": {"page_size": 21},
            "cursor": {"expected_cursor_ciphertext": "wrong-ciphertext"},
        }[changed]
    )
    with pytest.raises(KunlianSyncConflictError):
        await repo.stage_page(lease, **kwargs)
    await repo.mark_failed(lease, "RESUME_CONFLICT")
    async with sessions() as session:
        state = await session.get(KunlianConnectionState, "fixture")
        batch = await session.get(KunlianSyncBatch, lease.batch_id)
        assert state.active_batch_id == "previous-good"
        assert batch.status == "FAILED" and batch.reason_code == "RESUME_CONFLICT"
        assert batch.key_version == "key-v1" and batch.page_size == 20
        assert batch.cursor_ciphertext == "ciphertext-page-2"


async def test_old_fence_and_completed_page_cannot_write(directory_store):
    repo, sessions, clock, _ = directory_store
    first = await repo.claim_or_renew_lease("fixture", "a", key_version="key-v1", page_size=20)
    clock.advance(61)
    second = await repo.claim_or_renew_lease("fixture", "b", key_version="key-v1", page_size=20)
    with pytest.raises(KunlianSyncConflictError):
        await repo.stage_page(first, tenants=[], members=[], next_cursor_ciphertext=None)
    await repo.stage_page(second, tenants=[], members=[], next_cursor_ciphertext=None)
    with pytest.raises(KunlianSyncConflictError):
        await repo.stage_page(second, tenants=[], members=[], next_cursor_ciphertext=None)
    async with sessions() as session:
        assert (await session.get(KunlianSyncBatch, second.batch_id)).status == "VALIDATING"
        assert (await session.get(KunlianConnectionState, "fixture")).active_batch_id == "previous-good"


# T011 覆盖 AC-03, AC-05, AC-06, AC-09, AC-15, AC-16, AC-18, AC-20, AC-26。
ISSUER = "https://fixture.example"


def tenant(tid="external-a", status="ACTIVE"):
    return {"external_tenant_id": tid, "status": status, "version": "opaque-v0", "summary": {"name": tid}}


def member(mid="member-1", subject="subject-1", tid="external-a", status="ACTIVE", name="同名"):
    return {
        "external_tenant_id": tid,
        "member_id": mid,
        "subject": subject,
        "status": status,
        "deleted": False,
        "member_version": "opaque-z",
        "authorization_version": "opaque-a",
        "summary": {"name": name, "roles": [{"name": "admin", "status": "DISABLED"}]},
    }


async def publish(repo, *, tenants=None, members=None):
    lease = await repo.claim_or_renew_lease("fixture", "worker", key_version="key-v1", page_size=20)
    await repo.stage_page(
        lease,
        tenants=tenants if tenants is not None else [tenant()],
        members=members if members is not None else [member()],
        next_cursor_ciphertext=None,
    )
    await repo.publish_directory(lease, issuer=ISSUER)
    return lease


async def test_publish_full_directory_and_unchanged_revision(directory_store):
    from sqlmodel import select

    from bisheng.sso_sync.domain.models.kunlian import KunlianDirectoryMember, KunlianIdentityBinding

    repo, sessions, _, _ = directory_store
    await repo.bind_tenant("fixture", "external-a", verified_local_tenant_id=2, expected_revision=None)
    await repo.request_sync("fixture")
    await publish(
        repo,
        tenants=[tenant(), tenant("external-b")],
        members=[member(), member("other-member", "subject-1", "external-b")],
    )
    async with sessions() as session:
        bindings = (await session.exec(select(KunlianIdentityBinding))).all()
        assert len(bindings) == 1
        original = bindings[0]
        assert original.member_id != original.subject and original.local_user_id is None
        assert original.admission_status == "ACTIVE" and not original.local_override
        assert len((await session.exec(select(KunlianDirectoryMember))).all()) == 2
        revision, key = original.source_revision, original.identity_key
    second = await publish(repo)
    async with sessions() as session:
        binding = await session.get(KunlianIdentityBinding, key)
        assert binding.source_revision == revision
        assert (await session.get(KunlianConnectionState, "fixture")).active_batch_id == second.batch_id
        assert (await session.get(KunlianConnectionState, "fixture")).sync_completed_version == 1


@pytest.mark.parametrize("cause", ["DISABLED", "INVITED", "LEFT", "deleted", "missing", "tenant"])
async def test_unavailable_then_active_never_rewinds_auth_epoch(directory_store, cause):
    from sqlmodel import select

    from bisheng.sso_sync.domain.models.kunlian import KunlianIdentityBinding

    repo, sessions, _, _ = directory_store
    await repo.bind_tenant("fixture", "external-a", verified_local_tenant_id=2, expected_revision=None)
    await publish(repo)
    async with sessions() as session:
        old = (await session.exec(select(KunlianIdentityBinding))).one()
        identity_key, epoch = old.identity_key, old.auth_epoch
    item = member(status=cause if cause in {"DISABLED", "INVITED", "LEFT"} else "ACTIVE")
    item["deleted"] = cause == "deleted"
    await publish(
        repo,
        tenants=[tenant(status="DISABLED" if cause == "tenant" else "ACTIVE")],
        members=[] if cause == "missing" else [item],
    )
    async with sessions() as session:
        disabled = await session.get(KunlianIdentityBinding, identity_key)
        assert disabled.admission_status != "ACTIVE" and disabled.auth_epoch > epoch
        disabled_epoch = disabled.auth_epoch
    await publish(repo)
    async with sessions() as session:
        restored = await session.get(KunlianIdentityBinding, identity_key)
        assert restored.admission_status == "ACTIVE" and restored.auth_epoch == disabled_epoch


async def test_incomplete_or_conflicting_batch_does_not_publish(directory_store):
    from bisheng.common.errcode.sso_sync import KunlianDirectorySyncError

    repo, sessions, _, _ = directory_store
    lease = await repo.claim_or_renew_lease("fixture", "worker", key_version="key-v1", page_size=20)
    with pytest.raises(KunlianSyncConflictError):
        await repo.publish_directory(lease, issuer=ISSUER)
    await repo.stage_page(lease, tenants=[], members=[member()], next_cursor_ciphertext=None)
    with pytest.raises(KunlianDirectorySyncError):
        await repo.publish_directory(lease, issuer=ISSUER)
    async with sessions() as session:
        assert (await session.get(KunlianConnectionState, "fixture")).active_batch_id == "previous-good"


async def test_mapping_cas_manual_override_and_identity_rename(directory_store):
    from sqlmodel import select

    from bisheng.common.errcode.sso_sync import KunlianBindingConflictError
    from bisheng.sso_sync.domain.models.kunlian import KunlianIdentityBinding

    repo, sessions, _, _ = directory_store
    await repo.bind_tenant("fixture", "external-a", verified_local_tenant_id=2, expected_revision=None)
    with pytest.raises(KunlianBindingConflictError):
        await repo.bind_tenant("fixture", "external-b", verified_local_tenant_id=2, expected_revision=None)
    await publish(repo)
    async with sessions() as session:
        old = (await session.exec(select(KunlianIdentityBinding))).one()
        key, rev = old.identity_key, old.source_revision
    await repo.record_manual_override(key, True, expected_revision=rev)
    await publish(repo, members=[member(name="新名称")])
    async with sessions() as session:
        renamed = await session.get(KunlianIdentityBinding, key)
        assert renamed.source_revision != rev and renamed.local_override
        assert renamed.local_user_id is None
    with pytest.raises(KunlianBindingConflictError):
        await repo.record_manual_override(key, False, expected_revision=rev)


@pytest.mark.parametrize("conflict", ["member", "tenant"])
async def test_conflicting_page_rolls_back_and_cannot_publish(directory_store, conflict):
    from bisheng.common.errcode.sso_sync import KunlianDirectorySyncError

    repo, sessions, _, _ = directory_store
    lease = await repo.claim_or_renew_lease("fixture", "worker", key_version="key-v1", page_size=20)
    await repo.stage_page(lease, tenants=[tenant()], members=[member()], next_cursor_ciphertext="cursor-cipher")
    changed_tenant = tenant() | {"summary": {"name": "conflict"}}
    with pytest.raises(KunlianDirectorySyncError):
        await repo.stage_page(
            lease,
            tenants=[changed_tenant] if conflict == "tenant" else [],
            members=[member()] if conflict == "member" else [],
            expected_cursor_ciphertext="cursor-cipher",
            next_cursor_ciphertext=None,
        )
    with pytest.raises(KunlianSyncConflictError):
        await repo.publish_directory(lease, issuer=ISSUER)
    async with sessions() as session:
        assert (await session.get(KunlianSyncBatch, lease.batch_id)).cursor_ciphertext == "cursor-cipher"
        assert (await session.get(KunlianConnectionState, "fixture")).active_batch_id == "previous-good"


async def test_same_subject_in_two_tenants_stays_two_identities(directory_store):
    from sqlmodel import select

    from bisheng.sso_sync.domain.models.kunlian import KunlianIdentityBinding

    repo, sessions, _, _ = directory_store
    for external, local in [("external-a", 2), ("external-b", 3)]:
        await repo.bind_tenant("fixture", external, verified_local_tenant_id=local, expected_revision=None)
    await publish(repo, tenants=[tenant(), tenant("external-b")], members=[member(), member(tid="external-b")])
    async with sessions() as session:
        rows = (await session.exec(select(KunlianIdentityBinding))).all()
        assert len(rows) == 2 and len({r.identity_key for r in rows}) == 2
        assert {r.external_tenant_id for r in rows} == {"external-a", "external-b"}


# T015 覆盖 AC-05, AC-06, AC-15, AC-16, AC-19, AC-24, AC-26。
@pytest.fixture
def service_module():
    try:
        return import_module("bisheng.sso_sync.domain.services.kunlian_directory")
    except ModuleNotFoundError as exc:
        if exc.name != "bisheng.sso_sync.domain.services.kunlian_directory":
            raise
        pytest.fail("T016 directory service is not implemented", pytrace=False)


class PageClient:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.tokens = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def list_users(self, *, page_token=None):
        self.tokens.append(page_token)
        result = self.pages.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def directory_page(tid="tenant-1", mid="member-1", cursor=""):
    from bisheng.sso_sync.domain.clients.kunlian import DirectoryPage, DirectoryUser
    from test.sso.test_kunlian_directory_client import item

    value = item()
    value["tenant_id"] = value["tenant"]["id"] = tid
    value["id"] = mid
    return DirectoryPage((DirectoryUser.model_validate(value),), cursor, "fixture-request")


def make_service(module, repo, client, *, enabled=True):
    from pydantic import SecretStr

    from bisheng.core.config.sso_sync import KunlianConf

    credential = module.DirectoryCredential(version="key-v1", secret=SecretStr("fixture-key"))
    return module.KunlianDirectoryService(
        repo,
        KunlianConf(
            directory_enabled=enabled, connection_id="fixture", issuer=ISSUER, sync_key_reference="fixture-ref"
        ),
        credential_resolver=lambda _: credential,
        client_factory=lambda *a, **k: client,
    )


async def test_whole_sync_stores_all_tenants_and_reports_pending_projection(directory_store, service_module):
    repo, sessions, _, _ = directory_store
    await repo.bind_tenant("fixture", "tenant-1", verified_local_tenant_id=2, expected_revision=None)
    client = PageClient(directory_page(cursor="opaque-next"), directory_page("tenant-2", "member-2"))
    service = make_service(service_module, repo, client)
    await service.request_directory_sync("fixture", "MANUAL")
    result = await service.run_sync("fixture", "worker")
    assert result.directory_status == "PUBLISHED" and result.projection_status == "PENDING"
    assert result.member_count == 2 and result.unmapped_count == 1
    assert client.tokens == [None, "opaque-next"]
    async with sessions() as session:
        batch = await session.get(KunlianSyncBatch, result.batch_id)
        assert batch.cursor_ciphertext is None
        assert batch.counts["members"] == 2


@pytest.mark.parametrize("fail_after_page", [False, True])
async def test_failed_traversal_keeps_old_pointer_and_next_run_restarts(
    directory_store, service_module, fail_after_page
):
    from sqlmodel import select

    from bisheng.common.errcode.sso_sync import KunlianDirectorySyncError
    from bisheng.sso_sync.domain.clients.kunlian import KunlianDirectoryRequestError

    repo, sessions, _, _ = directory_store
    pages = [directory_page(cursor="private-cursor")] if fail_after_page else []
    client = PageClient(*pages, KunlianDirectoryRequestError(503, "UNAVAILABLE"))
    service = make_service(service_module, repo, client)
    with pytest.raises(KunlianDirectorySyncError):
        await service.run_sync("fixture", "worker")
    async with sessions() as session:
        assert (await session.get(KunlianConnectionState, "fixture")).active_batch_id == "previous-good"
        batch = (await session.exec(select(KunlianSyncBatch))).one()
        assert batch.status == "FAILED" and batch.reason_code == "UPSTREAM_UNAVAILABLE"
        assert batch.cursor_ciphertext != "private-cursor"
        if fail_after_page:
            assert isinstance(batch.cursor_ciphertext, str)
    restarted = PageClient(directory_page())
    await make_service(service_module, repo, restarted).run_sync("fixture", "worker")
    assert restarted.tokens == [None]


async def test_empty_success_and_new_request_during_fetch_are_distinct(directory_store, service_module):
    from bisheng.sso_sync.domain.clients.kunlian import DirectoryPage

    repo, _, _, _ = directory_store
    await repo.request_sync("fixture")

    class NewDemandClient(PageClient):
        async def list_users(self, *, page_token=None):
            await repo.request_sync("fixture")
            return await super().list_users(page_token=page_token)

    result = await make_service(service_module, repo, NewDemandClient(DirectoryPage((), ""))).run_sync(
        "fixture", "worker"
    )
    status = await repo.get_status("fixture")
    assert result.directory_status == "PUBLISHED" and result.member_count == 0
    assert status["sync_requested_version"] == 2 and status["sync_completed_version"] == 1


async def test_disabled_sync_has_no_network_or_batch(directory_store, service_module):
    from sqlmodel import select

    from bisheng.common.errcode.sso_sync import KunlianDirectoryNotReadyError

    repo, sessions, _, _ = directory_store
    client = PageClient()
    with pytest.raises(KunlianDirectoryNotReadyError):
        await make_service(service_module, repo, client, enabled=False).run_sync("fixture", "worker")
    assert client.tokens == []
    async with sessions() as session:
        assert not (await session.exec(select(KunlianSyncBatch))).all()


@pytest.mark.parametrize(
    "status,code,reason",
    [
        (401, "UNAUTHENTICATED", "CREDENTIAL_INVALID"),
        (403, "PERMISSION_DENIED", "ACCESS_DENIED"),
        (403, "PROTOCOL_ERROR", "NETWORK_ACCESS_DENIED"),
    ],
)
async def test_upstream_refusal_persists_distinct_diagnostics(directory_store, service_module, status, code, reason):
    from bisheng.common.errcode.sso_sync import KunlianDirectorySyncError
    from bisheng.sso_sync.domain.clients.kunlian import KunlianDirectoryRequestError

    repo, _, _, _ = directory_store
    client = PageClient(KunlianDirectoryRequestError(status, code))
    with pytest.raises(KunlianDirectorySyncError):
        await make_service(service_module, repo, client).run_sync("fixture", "worker")
    assert (await repo.get_status("fixture"))["last_reason_code"] == reason


async def test_cursor_encryption_failure_cannot_finalize_or_disappear(directory_store, service_module):
    from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError

    repo, _, _, _ = directory_store
    service = make_service(service_module, repo, PageClient(directory_page(cursor="private-cursor")))
    service.encrypt_cursor = lambda _: None
    with pytest.raises(KunlianDependencyUnavailableError):
        await service.run_sync("fixture", "worker")
    status = await repo.get_status("fixture")
    assert status["directory_status"] == "FAILED" and status["active_batch_id"] == "previous-good"


async def test_narrow_user_mapping_requires_current_materialized_binding(directory_store):
    from sqlmodel import select

    from bisheng.common.errcode.sso_sync import KunlianDirectoryNotReadyError, KunlianIdentityUnavailableError
    from bisheng.sso_sync.application import kunlian as application
    from bisheng.sso_sync.domain.models.kunlian import KunlianIdentityBinding, KunlianTenantBinding

    repo, sessions, _, _ = directory_store
    await repo.bind_tenant("fixture", "external-a", verified_local_tenant_id=2, expected_revision=None)
    await publish(repo)
    async with sessions() as session:
        state = await session.get(KunlianConnectionState, "fixture")
        state.enabled = True
        binding = (await session.exec(select(KunlianIdentityBinding))).one()
        binding.local_user_id = 17
        session.add(state)
        session.add(binding)
        await session.commit()
    if not hasattr(application, "resolve_external_tenant_mapping"):
        pytest.fail("T026 restricted mapping authority is not implemented", pytrace=False)
    with pytest.raises(KunlianDirectoryNotReadyError):
        await application.resolve_external_tenant_mapping(17, repository=repo)
    async with sessions() as session:
        binding = (await session.exec(select(KunlianIdentityBinding))).one()
        binding.projection_status, binding.projected_revision = "SUCCEEDED", binding.source_revision
        mapping_row = await session.get(KunlianTenantBinding, ("fixture", "external-a"))
        mapping_row.materialized = True
        session.add(binding)
        session.add(mapping_row)
        await session.commit()
    assert (await application.resolve_external_tenant_mapping(17, repository=repo)).local_tenant_id == 2
    async with sessions() as session:
        row = await session.get(KunlianTenantBinding, ("fixture", "external-a"))
        row.enabled = False
        session.add(row)
        await session.commit()
    with pytest.raises(KunlianIdentityUnavailableError):
        await application.resolve_external_tenant_mapping(17, repository=repo)
