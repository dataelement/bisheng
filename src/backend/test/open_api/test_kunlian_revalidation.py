from types import SimpleNamespace

import pytest


async def test_worker_reference_revalidation_refuses_changed_user():
    from bisheng.open_api.application import kunlian_access

    assert hasattr(kunlian_access, "revalidate_kunlian_subject"), "worker reference verifier missing"
    subject = SimpleNamespace(
        credential_id=1,
        connection_id="integration",
        identity_connection_id="sso",
        external_tenant_id="external",
        external_user_id="subject",
        tenant_id=7,
        user_id=17,
    )

    class Credentials:
        async def validate_reference(self, key_id, **kwargs):
            assert kwargs["integration_id"] == "integration"
            assert kwargs["connection_id"] == "sso"

    class Identities:
        async def resolve(self, **kwargs):
            return SimpleNamespace(user_id=18, tenant_id=7, is_global_super=False)

    with pytest.raises(kunlian_access.KunlianAccessError, match="FORBIDDEN"):
        await kunlian_access.revalidate_kunlian_subject(subject, credentials=Credentials(), identities=Identities())
