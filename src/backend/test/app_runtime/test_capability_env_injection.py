"""The capability-environment seam on the start path (F055 T056 / AC-49).

F054 brings a container up; F055 mints the credential it starts with. The seam
between them is a registry, for the same reason ``lifecycle_hooks`` is one: the
runtime layer must not import the publish pipeline (RULE-5).

Three properties, and a start path that quietly loses any one of them ships an
application whose model calls 403 with nothing saying why:

* the provider is asked with the **version about to run**, not the one running;
* what it returns **wins** over the version's own injections — the reserved
  names belong to the platform (F054 contract §5);
* a provider that fails **stops the start** rather than bringing up a container
  without the credential it was promised.
"""

from __future__ import annotations

import pytest

from bisheng.app_runtime.domain.constants import AppState
from bisheng.app_runtime.domain.services import runtime_env_ports

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clear_provider():
    runtime_env_ports.clear_capability_env_provider()
    yield
    runtime_env_ports.clear_capability_env_provider()


def _deploy_kwargs(fake_orchestrator) -> dict:
    return next(kwargs for name, kwargs in fake_orchestrator.calls if name == "deploy")


async def test_without_a_provider_the_start_path_is_unchanged(app_db, app_factory, app_owner, fake_orchestrator):
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    app, _version = await app_factory(state=AppState.PENDING_CAPACITY.value)

    await AppStateService.manual_publish(app.id, actor=app_owner.payload)

    # No capability bus wired in this process: F054's own variables and nothing
    # else, which is the honest state of affairs rather than a failed start.
    assert _deploy_kwargs(fake_orchestrator)["env"] == {}


async def test_the_provider_sees_the_version_about_to_run(app_db, app_factory, app_owner, fake_orchestrator):
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    seen: list[dict] = []

    async def _provider(*, app_id, capabilities):
        seen.append({"app_id": app_id, "capabilities": capabilities})
        return {"BISHENG_APP_TOKEN": "bs-app-plaintext"}

    runtime_env_ports.register_capability_env_provider(_provider)
    app, version = await app_factory(state=AppState.PENDING_CAPACITY.value)

    await AppStateService.manual_publish(app.id, actor=app_owner.payload)

    assert seen == [{"app_id": app.id, "capabilities": version.capabilities}]
    assert _deploy_kwargs(fake_orchestrator)["env"]["BISHENG_APP_TOKEN"] == "bs-app-plaintext"


async def test_platform_reserved_names_win_over_the_versions_own_injections(
    app_db, app_factory, app_owner, fake_orchestrator
):
    """F054 contract §5: 平台保留 env 名覆盖调用方同名值."""
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService
    from bisheng.database.models.app_version import AppVersionDao

    async def _provider(*, app_id, capabilities):
        return {"BISHENG_APP_TOKEN": "minted-now"}

    runtime_env_ports.register_capability_env_provider(_provider)
    app, version = await app_factory(state=AppState.PENDING_CAPACITY.value)
    async with app_db() as session:
        row = await AppVersionDao.aget(session, app.id, version.id)
        row.injections = {"env": {"BISHENG_APP_TOKEN": "stale", "APP_OWN_FLAG": "1"}}
        session.add(row)
        await session.commit()

    await AppStateService.manual_publish(app.id, actor=app_owner.payload)

    env = _deploy_kwargs(fake_orchestrator)["env"]
    assert env["BISHENG_APP_TOKEN"] == "minted-now"
    # The application's own variables are untouched; only the reserved name is.
    assert env["APP_OWN_FLAG"] == "1"


async def test_a_failing_provider_stops_the_start_rather_than_serving_a_broken_app(
    app_db, app_factory, app_owner, fake_orchestrator
):
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    async def _provider(*, app_id, capabilities):
        raise RuntimeError("credential subject unavailable")

    runtime_env_ports.register_capability_env_provider(_provider)
    app, _version = await app_factory(state=AppState.PENDING_CAPACITY.value)

    with pytest.raises(RuntimeError):
        await AppStateService.manual_publish(app.id, actor=app_owner.payload)

    # Nothing was deployed: a container without the credential it was promised
    # would give the application's users a broken feature and no error anywhere.
    assert [name for name, _ in fake_orchestrator.calls] == ["admission"]


async def test_registering_and_clearing_is_the_whole_api():
    """The seam stays a seam: no second way in, no per-call configuration."""
    assert set(runtime_env_ports.__all__) == {
        "CapabilityEnvProvider",
        "capability_env",
        "clear_capability_env_provider",
        "register_capability_env_provider",
    }
    assert await runtime_env_ports.capability_env(app_id="x", capabilities={}) == {}
