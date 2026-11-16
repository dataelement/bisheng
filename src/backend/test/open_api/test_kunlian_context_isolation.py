from types import SimpleNamespace


async def test_business_scope_clears_inherited_management_override():
    from bisheng.core.context.tenant import (
        bypass_tenant_filter,
        get_current_tenant_id,
        is_tenant_filter_bypassed,
        management_tenant_scope,
    )
    from bisheng.open_api.application.kunlian_access import KunlianAccessService

    class Credentials:
        async def authenticate_caller(self, authorization, *, capability):
            assert (authorization, capability) == ("Bearer synthetic", "read")
            return SimpleNamespace(connection_id="c", integration_id="i", credential_id=1)

        async def validate_reference(
            self, credential_id, *, integration_id, connection_id, external_tenant_id, capability
        ):
            assert (credential_id, integration_id, connection_id, external_tenant_id, capability) == (
                1,
                "i",
                "c",
                "a",
                "read",
            )
            return SimpleNamespace(connection_id="c", integration_id="i", credential_id=1, external_tenant_id="a")

    class Accounts:
        async def resolve_account(self, connection_id, user_account):
            assert (connection_id, user_account) == ("c", "member-account")
            return SimpleNamespace(user_id=17, tenant_id=7, external_tenant_id="a", external_user_id="u")

    class Identities:
        async def resolve(self, *, connection_id, external_tenant_id, external_user_id):
            assert (connection_id, external_tenant_id, external_user_id) == ("c", "a", "u")
            return SimpleNamespace(user_id=17, tenant_id=7)

    async def privilege(user):
        return False, False

    service = KunlianAccessService(Credentials(), Identities(), privilege_reader=privilege, account_resolver=Accounts())
    with management_tenant_scope(99), bypass_tenant_filter():
        async with service.use_user("Bearer synthetic", "member-account", capability="read"):
            assert get_current_tenant_id() == 7
            assert not is_tenant_filter_bypassed()
        assert get_current_tenant_id() == 99
        assert is_tenant_filter_bypassed()
