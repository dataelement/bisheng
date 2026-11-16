"""SG 式依赖必须在同一作用域限定并复原业务租户。"""

import importlib
from types import SimpleNamespace

import pytest


def access_module():
    name = "bisheng.open_api.application.kunlian_access"
    assert importlib.util.find_spec(name) is not None, "F133 user context is not implemented"
    return importlib.import_module(name)


class Credentials:
    async def authenticate_caller(self, authorization, *, capability):
        assert authorization == "Bearer synthetic"
        assert capability in {"read", "write"}
        return SimpleNamespace(
            connection_id="kunlian",
            integration_id="main",
            credential_id=1,
            capabilities=frozenset({"read", "write"}),
            policy_revision=1,
        )

    async def validate_reference(self, credential_id, *, integration_id, connection_id, external_tenant_id, capability):
        assert (credential_id, integration_id, connection_id, external_tenant_id) == (1, "main", "kunlian", "tenant-a")
        assert capability in {"read", "write"}
        return SimpleNamespace(
            connection_id="kunlian",
            integration_id="main",
            credential_id=1,
            external_tenant_id=external_tenant_id,
            capabilities=frozenset({"read", "write"}),
            policy_revision=1,
        )


class Accounts:
    async def resolve_account(self, connection_id, user_account):
        assert (connection_id, user_account) == ("kunlian", "member-account")
        return SimpleNamespace(user_id=17, tenant_id=7, external_tenant_id="tenant-a", external_user_id="subject-a")


class Identities:
    async def resolve(self, *, connection_id, external_tenant_id, external_user_id):
        assert (connection_id, external_tenant_id, external_user_id) == ("kunlian", "tenant-a", "subject-a")
        return SimpleNamespace(user_id=17, tenant_id=7, user_name="member")


async def test_request_user_context_restores_tenant_after_failure():
    module = access_module()
    from bisheng.core.context.tenant import current_tenant_id, visible_tenant_ids
    from bisheng.permission.application.identity import get_current_permission_actor

    async def privilege(user):
        return False, True

    service = module.KunlianAccessService(
        Credentials(), Identities(), privilege_reader=privilege, account_resolver=Accounts()
    )
    token = current_tenant_id.set(19)
    visible = visible_tenant_ids.set(frozenset({19}))
    try:
        with pytest.raises(RuntimeError, match="business failure"):
            async with service.use_user("Bearer synthetic", "member-account", capability="write") as access:
                assert access.user.user_id == 17
                assert access.user_account == "member-account"
                assert (access.external_tenant_id, access.external_user_id) == ("tenant-a", "subject-a")
                assert access.credential.external_tenant_id == "tenant-a"
                assert current_tenant_id.get() == 7
                assert visible_tenant_ids.get() == frozenset({7})
                actor = get_current_permission_actor()
                assert actor.tenant_admin_tenant_ids == frozenset({7})
                raise RuntimeError("business failure")
        assert current_tenant_id.get() == 19
        assert visible_tenant_ids.get() == frozenset({19})
    finally:
        current_tenant_id.reset(token)
        visible_tenant_ids.reset(visible)


async def test_request_user_context_refuses_global_super():
    module = access_module()

    async def privilege(user):
        return True, True

    service = module.KunlianAccessService(
        Credentials(), Identities(), privilege_reader=privilege, account_resolver=Accounts()
    )
    with pytest.raises(module.KunlianAccessError, match="FORBIDDEN"):
        async with service.use_user("Bearer synthetic", "member-account", capability="read"):
            pytest.fail("global super must never become the delegated business actor")


@pytest.mark.parametrize("identity_ids", [(18, 7), (17, 8)], ids=["different-user", "different-tenant"])
async def test_request_user_context_refuses_identity_payload_inconsistent_with_account_facts(identity_ids):
    module = access_module()
    from bisheng.core.context.tenant import current_tenant_id, visible_tenant_ids

    class InconsistentIdentities:
        async def resolve(self, **kwargs):
            return SimpleNamespace(user_id=identity_ids[0], tenant_id=identity_ids[1])

    async def privilege(user):
        return False, False

    service = module.KunlianAccessService(
        Credentials(), InconsistentIdentities(), privilege_reader=privilege, account_resolver=Accounts()
    )
    token = current_tenant_id.set(19)
    visible = visible_tenant_ids.set(frozenset({19}))
    try:
        with pytest.raises(module.KunlianAccessError, match="FORBIDDEN"):
            async with service.use_user("Bearer synthetic", "member-account", capability="read"):
                pytest.fail("identity payload must agree with authoritative account facts")
        assert current_tenant_id.get() == 19
        assert visible_tenant_ids.get() == frozenset({19})
    finally:
        current_tenant_id.reset(token)
        visible_tenant_ids.reset(visible)
