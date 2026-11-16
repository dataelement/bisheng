"""F133 Key 认证独立于 SG 式业务用户解析。"""

import importlib
from datetime import UTC, datetime, timedelta

import pytest


def service_module():
    name = "bisheng.open_api.domain.services.kunlian_credential"
    assert importlib.util.find_spec(name) is not None, "F133 credential service is not implemented"
    return importlib.import_module(name)


class Store:
    def __init__(self):
        self.rows = {}

    async def insert(self, row):
        row.id = len(self.rows) + 1
        self.rows[row.id] = row
        return row

    async def by_hash(self, digest):
        return next((row for row in self.rows.values() if row.token_hash == digest), None)

    async def get(self, key_id):
        return self.rows.get(key_id)

    async def save(self, row, *, expected_revision):
        if self.rows[row.id].policy_revision != expected_revision:
            return False
        self.rows[row.id] = row
        return True

    async def rotate(self, old, new, *, expected_revision):
        if not await self.save(old, expected_revision=expected_revision):
            return None
        return await self.insert(new)

    async def list(self, *, offset, limit):
        return list(self.rows.values())[offset : offset + limit]


async def test_key_authentication_limits_tenants_and_capabilities():
    module = service_module()
    store = Store()
    service = module.KunlianCredentialService(store)
    issued = await service.issue(
        is_global_super=True,
        created_by=1,
        connection_id="kunlian",
        integration_id="kunlian-main",
        tenant_ids=["a", "b"],
        capabilities=["read", "invoke"],
    )
    key = issued["api_key"]
    assert key not in repr(store.rows)
    principal = await service.authenticate("Bearer " + key, external_tenant_id="b", capability="invoke")
    assert principal.integration_id == "kunlian-main"
    with pytest.raises(module.KunlianAccessError, match="FORBIDDEN"):
        await service.authenticate("Bearer " + key, external_tenant_id="c", capability="read")
    with pytest.raises(module.KunlianAccessError, match="FORBIDDEN"):
        await service.authenticate("Bearer " + key, external_tenant_id="a", capability="grant")
    await service.revoke(issued["id"], is_global_super=True)
    with pytest.raises(module.KunlianAccessError, match="UNAUTHENTICATED"):
        await service.authenticate("Bearer " + key, external_tenant_id="a", capability="read")


async def test_rotation_preserves_identity_and_scope_updates_take_effect():
    module = service_module()
    store = Store()
    service = module.KunlianCredentialService(store)
    issued = await service.issue(
        is_global_super=True,
        created_by=1,
        connection_id="c",
        integration_id="i",
        tenant_ids=["a", "b"],
        capabilities=["read", "invoke"],
    )
    for action in (service.revoke, service.rotate, service.update):
        with pytest.raises(module.KunlianAccessError, match="FORBIDDEN"):
            await action(issued["id"], is_global_super=False)
    await service.update(issued["id"], is_global_super=True, tenant_ids=["a"], capabilities=["read"])
    with pytest.raises(module.KunlianAccessError, match="FORBIDDEN"):
        await service.authenticate("Bearer " + issued["api_key"], external_tenant_id="b", capability="read")
    rotated = await service.rotate(issued["id"], is_global_super=True, created_by=2)
    assert rotated["api_key"] != issued["api_key"]
    assert rotated["integration_id"] == "i"
    assert rotated["connection_id"] == "c"
    assert rotated["tenant_ids"] == ["a"]
    assert rotated["rotated_from_id"] == issued["id"]
    with pytest.raises(module.KunlianAccessError, match="UNAUTHENTICATED"):
        await service.authenticate("Bearer " + issued["api_key"], external_tenant_id="a", capability="read")
    principal = await service.authenticate("Bearer " + rotated["api_key"], external_tenant_id="a", capability="read")
    assert principal.credential_id == rotated["id"]
    assert "token_hash" not in rotated
    assert "api_key" not in (await service.list(is_global_super=True))[0]
    assert "token_hash" not in repr(principal)


async def test_authentication_fails_closed_on_store_error_and_expiry():
    module = service_module()
    store = Store()
    service = module.KunlianCredentialService(store)
    issued = await service.issue(
        is_global_super=True,
        created_by=1,
        connection_id="c",
        integration_id="i",
        tenant_ids=["a"],
        capabilities=["read"],
    )
    store.rows[issued["id"]].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(module.KunlianAccessError, match="UNAUTHENTICATED"):
        await service.authenticate("Bearer " + issued["api_key"], external_tenant_id="a", capability="read")

    async def broken(_digest):
        raise RuntimeError("database unavailable")

    store.by_hash = broken
    with pytest.raises(module.KunlianAccessError, match="UNAVAILABLE"):
        await service.authenticate("Bearer " + issued["api_key"], external_tenant_id="a", capability="read")


@pytest.mark.parametrize("authorization", [None, "", "Basic x", "Bearer bs-sak-other", "Bearer a b"])
async def test_malformed_keys_are_rejected(authorization):
    module = service_module()
    with pytest.raises(module.KunlianAccessError, match="UNAUTHENTICATED"):
        await module.KunlianCredentialService(Store()).authenticate(
            authorization, external_tenant_id="a", capability="read"
        )


async def test_repository_rotation_is_atomic_and_rejects_stale_policy(open_api_db, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from bisheng.open_api.domain.models.kunlian_credential import KunlianCredential
    from bisheng.open_api.domain.repositories import kunlian_credential as repository_module

    async with open_api_db() as session:
        await session.run_sync(lambda sync: KunlianCredential.__table__.create(sync.connection()))
    monkeypatch.setattr(repository_module, "get_async_db_session", open_api_db)
    service = service_module().KunlianCredentialService()
    issued = await service.issue(
        is_global_super=True,
        created_by=1,
        connection_id="c",
        integration_id="i",
        tenant_ids=["a"],
        capabilities=["read"],
    )
    repo = service.store
    stale = await repo.get(issued["id"])
    await service.update(issued["id"], is_global_super=True, tenant_ids=["b"])
    stale.policy_revision += 1
    stale.tenant_ids = ["a"]
    assert not await repo.save(stale, expected_revision=1)
    old = await repo.get(issued["id"])
    new = KunlianCredential(
        **({name: getattr(old, name) for name in KunlianCredential.model_fields} | {"id": None})
    )  # duplicate digest must roll back old revocation
    old.revoked_at = datetime.now(UTC).replace(tzinfo=None)
    old.policy_revision += 1
    with pytest.raises(IntegrityError):
        await repo.rotate(old, new, expected_revision=2)
    assert (await repo.get(issued["id"])).revoked_at is None
    rotated = await service.rotate(issued["id"], is_global_super=True, created_by=2)
    assert rotated["tenant_ids"] == ["b"]
    assert (await repo.get(issued["id"])).revoked_at is not None
    assert (await repo.by_hash(__import__("hashlib").sha256(rotated["api_key"].encode()).hexdigest())).id == rotated[
        "id"
    ]


async def test_detail_requires_super_and_never_discloses_key_material():
    module = service_module()
    service = module.KunlianCredentialService(Store())
    issued = await service.issue(
        is_global_super=True,
        created_by=1,
        connection_id="c",
        integration_id="i",
        tenant_ids=["a"],
        capabilities=["read"],
    )
    with pytest.raises(module.KunlianAccessError, match="FORBIDDEN"):
        await service.detail(issued["id"], is_global_super=False)
    with pytest.raises(module.KunlianAccessError, match="NOT_FOUND"):
        await service.detail(999, is_global_super=True)
    item = await service.detail(issued["id"], is_global_super=True)
    assert item["key_mask"] == issued["key_mask"]
    assert "api_key" not in item
    assert "token_hash" not in item
    item["tenant_ids"].append("untrusted")
    assert (await service.detail(issued["id"], is_global_super=True))["tenant_ids"] == ["a"]


async def test_worker_reference_revalidates_current_policy_without_secret():
    module = service_module()
    store = Store()
    service = module.KunlianCredentialService(store)
    issued = await service.issue(
        is_global_super=True,
        created_by=1,
        connection_id="c",
        integration_id="i",
        tenant_ids=["a"],
        capabilities=["invoke"],
    )
    reference = {"integration_id": "i", "connection_id": "c", "external_tenant_id": "a", "capability": "invoke"}
    principal = await service.validate_reference(issued["id"], **reference)
    assert principal.credential_id == issued["id"]
    for field, value in [
        ("integration_id", "other"),
        ("connection_id", "other"),
        ("external_tenant_id", "b"),
        ("capability", "grant"),
    ]:
        with pytest.raises(module.KunlianAccessError, match="FORBIDDEN"):
            await service.validate_reference(issued["id"], **(reference | {field: value}))
    with pytest.raises(module.KunlianAccessError, match="UNAUTHENTICATED"):
        await service.validate_reference(999, **reference)
    await service.update(issued["id"], is_global_super=True, capabilities=["read"])
    with pytest.raises(module.KunlianAccessError, match="FORBIDDEN"):
        await service.validate_reference(issued["id"], **reference)
    await service.revoke(issued["id"], is_global_super=True)
    with pytest.raises(module.KunlianAccessError, match="UNAUTHENTICATED"):
        await service.validate_reference(issued["id"], **reference)
    store.rows[issued["id"]].revoked_at = None
    store.rows[issued["id"]].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(module.KunlianAccessError, match="UNAUTHENTICATED"):
        await service.validate_reference(issued["id"], **reference)

    async def broken(_key_id):
        raise RuntimeError("database unavailable")

    store.get = broken
    with pytest.raises(module.KunlianAccessError, match="UNAVAILABLE"):
        await service.validate_reference(issued["id"], **reference)


async def test_caller_authentication_precedes_server_resolved_tenant_scope():
    module = service_module()
    service = module.KunlianCredentialService(Store())
    issued = await service.issue(
        is_global_super=True,
        created_by=1,
        connection_id="kunlian",
        integration_id="main",
        tenant_ids=["a"],
        capabilities=["read"],
    )
    assert hasattr(service, "authenticate_caller"), "account admission needs caller-only credential verification"
    caller = await service.authenticate_caller("Bearer " + issued["api_key"], capability="read")
    assert caller.connection_id == "kunlian"
    with pytest.raises(module.KunlianAccessError, match="FORBIDDEN"):
        await service.validate_reference(
            caller.credential_id,
            integration_id=caller.integration_id,
            connection_id=caller.connection_id,
            external_tenant_id="not-allowed",
            capability="read",
        )
    with pytest.raises(module.KunlianAccessError, match="FORBIDDEN"):
        await service.authenticate_caller("Bearer " + issued["api_key"], capability="write")


async def test_key_issuance_requires_platform_super_and_future_expiry():
    module = service_module()
    service = module.KunlianCredentialService(Store())
    arguments = {
        "created_by": 1,
        "connection_id": "kunlian",
        "integration_id": "main",
        "tenant_ids": ["a"],
        "capabilities": ["read"],
    }
    with pytest.raises(module.KunlianAccessError, match="FORBIDDEN"):
        await service.issue(is_global_super=False, **arguments)
    with pytest.raises(module.KunlianAccessError, match="INVALID_INPUT"):
        await service.issue(is_global_super=True, expires_at=datetime.now(UTC) - timedelta(seconds=1), **arguments)
