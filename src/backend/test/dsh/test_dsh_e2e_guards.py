"""Local harness safety checks; no live service or credential is used."""

from types import SimpleNamespace

import pytest

from test.dsh.test_dsh_e2e import live


@pytest.mark.parametrize(
    "values,reason",
    [
        ({}, "Live DSH disabled"),
        ({"DSH_E2E_RUN": "1"}, "ISOLATED_ENVIRONMENT"),
        ({"DSH_E2E_RUN": "1", "DSH_E2E_ISOLATED_ENVIRONMENT": "1"}, "DSH_E2E_BASE or DSH_E2E_MANIFEST"),
    ],
)
async def test_incomplete_live_opt_in_never_constructs_network_client(monkeypatch, values, reason):
    from test.dsh import test_dsh_e2e as module

    for key in ("DSH_E2E_RUN", "DSH_E2E_ISOLATED_ENVIRONMENT", "DSH_E2E_BASE", "DSH_E2E_MANIFEST"):
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    def forbidden_client(**_kwargs):
        pytest.fail("A network client was constructed before configuration gates")

    monkeypatch.setattr(module.httpx, "AsyncClient", forbidden_client)
    request = SimpleNamespace(config=SimpleNamespace())
    generator = live.__wrapped__(request)
    with pytest.raises(pytest.skip.Exception, match=reason):
        await anext(generator)
    await generator.aclose()
