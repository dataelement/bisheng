"""覆盖 AC: AC-05, AC-06, AC-13。与网关使用同组精确组合。"""

import pytest
from pydantic import SecretStr

from bisheng.common.errcode.sso_sync import KunlianIdentityUnavailableError, KunlianLoginInvalidError
from bisheng.sso_sync.domain.clients.kunlian import KunlianTokenBinding
from test.sso import test_kunlian_idp_client as fixtures
from test.sso.test_kunlian_admission import config

harness = fixtures.harness
signing_key = fixtures.signing_key


def test_map_registration_uses_pairs_without_obsolete_fixed_fields():
    conf = config()
    conf.login_scope_mode = "tenant_workspace_map"
    conf.tenant_workspace_allowlist = {"A": ["WA"], "B": ["WB"]}
    conf.allowed_tenant_id = ""
    conf.allowed_workspace_ids = []
    assert conf.readiness_reasons(multi_tenant_enabled=True) == ()


@pytest.mark.parametrize(("tenant", "workspace", "allowed"), [("A", "WA", True), ("B", "WB", True), ("A", "WB", False)])
async def test_rs256_and_introspection_both_enforce_exact_scope(harness, tenant, workspace, allowed):
    client, state, _, token = harness
    conf = client._config.model_copy(deep=True)
    conf.login_scope_mode = "tenant_workspace_map"
    conf.tenant_workspace_allowlist = {"A": ["WA"], "B": ["WB"]}
    conf.allowed_tenant_id, conf.allowed_workspace_ids = "", []
    transport, clock = client._client._transport, client._clock
    await client._client.aclose()
    client = type(client)(conf, client_secret=SecretStr("fixture+secret"), transport=transport, clock=clock)
    state["claims"].update(tenant_id=tenant, workspace_id=workspace)
    state["introspection"].update(tenant_id=tenant, workspace_id=workspace)
    async with client:
        if not allowed:
            with pytest.raises(KunlianLoginInvalidError):
                await client.verify_id_token(token(), expected_nonce="fixture-nonce")
            expected = KunlianTokenBinding(
                conf.issuer, conf.client_id, state["claims"]["sub"], tenant, workspace, state["claims"]["sid"]
            )
            with pytest.raises(KunlianIdentityUnavailableError):
                await client.introspect(SecretStr("opaque+AT"), expected=expected)
        else:
            identity = await client.verify_id_token(token(), expected_nonce="fixture-nonce")
            assert (
                await client.introspect(SecretStr("opaque+AT"), expected=identity)
            ).expires_at == identity.expires_at
