"""覆盖 AC: AC-01、AC-24、AC-25、AC-27、AC-28、AC-42、AC-54."""

from types import SimpleNamespace

import pytest

from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
from bisheng.app_runtime.domain.services.runtime_profile_service import RuntimeProfileService


@pytest.mark.parametrize(
    "executor,mode,requires_profile",
    [
        ("kubernetes", "source-image", True),
        ("docker", "source-image", False),
        ("kubernetes", "image", False),
        ("kubernetes", "bundle", True),
    ],
)
async def test_prepare_freezes_the_execution_profile_only_where_needed(monkeypatch, executor, mode, requires_profile):
    seen = []
    profile = {"profile_id": "frozen", "profile_digest": "a" * 64, "platform": "linux/amd64"}

    class Repository:
        async def find(self, *args, **kwargs):
            return []

        async def get_application(self, app_id):
            return SimpleNamespace(id=app_id, slug="fixture", tenant_id=1)

        async def freeze_delivery(self, row):
            return row

    class Coordinator(RuntimeDeliveryCoordinator):
        async def node(self, app):
            return SimpleNamespace(platform="linux/amd64", executor_kind=executor), None

        async def source(self, deployment):
            return SimpleNamespace(id="source")

        async def submit(self, app, **kwargs):
            seen.append(kwargs["payload"])
            return SimpleNamespace(id="op")

        async def wake(self, operation):
            pass

        async def wait(self, operation):
            return {"result": {"delivery": {"mode": mode}}}

    async def resolve(self, language, reference, platform):
        assert (language, platform) == ("python3.11", "linux/amd64")
        return profile

    monkeypatch.setattr(RuntimeProfileService, "resolve", resolve)
    manifest = SimpleNamespace(
        runtime="python3.11", delivery=SimpleNamespace(model_dump=lambda **_: {"mode": mode}), port=8080
    )
    deployment = SimpleNamespace(id="deployment", app_id="app-a", version_id="version", tenant_id=1)
    await Coordinator(Repository()).prepare(deployment, manifest, SimpleNamespace(memory_mb=512, cpu_millicores=250))
    assert bool(seen[0]["profile"]) is requires_profile
    if requires_profile:
        assert seen[0]["profile"] == profile
