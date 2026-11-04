"""覆盖 AC: AC-01、AC-24、AC-25、AC-27、AC-28、AC-36、AC-42、AC-46、AC-54、AC-56."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
from bisheng.app_runtime.domain.services.runtime_profile_service import RuntimeProfileService
from test.app_runtime.test_runtime_delivery_repository import operation
from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo


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


@pytest.mark.parametrize("supplied_base", [None, "https://caller.example"])
@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize("models", [False, True])
async def test_v2_environment_satisfies_shipped_sdk_contract_and_preserves_other_handles(
    runtime_repo, monkeypatch, preview, models, supplied_base
):
    """AC-36, AC-46, AC-56: the shipped SDK consumes the persisted platform-owned address."""
    from cryptography.fernet import Fernet

    from bisheng.app_publish.domain.services import capability_bus_service
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.app_runtime.domain.services.runtime_payload import unseal
    from bisheng.common.services.config_service import settings

    base = "https://platform.example"
    model_base = base + "/api/v2/models/v1"
    monkeypatch.setattr(settings.app_runtime, "runtime_platform_base_url", base)
    monkeypatch.setattr(settings.app_runtime, "runtime_payload_key", Fernet.generate_key().decode())
    monkeypatch.setattr(capability_bus_service, "model_face_base_url", lambda: model_base)
    staged = []

    async def stage(app_id, *, operation, scopes, repository):
        staged.append((app_id, operation.id, scopes))
        return "fixture-app-token"

    monkeypatch.setattr(AppRuntimeCredentialService, "stage", stage)
    op = operation()
    op.kind = "preview" if preview else "deploy"
    op = await runtime_repo.create_operation(op)
    coordinator = RuntimeDeliveryCoordinator(runtime_repo, control=SimpleNamespace())
    await coordinator.inject_environment(
        op,
        capabilities={"models": [{"name": "fixture-model"}]} if models else {},
        environment={
            "APP_CUSTOM_FLAG": "kept",
            **({"BISHENG_PLATFORM_API_BASE": supplied_base} if supplied_base else {}),
        },
        preview=preview,
    )
    saved = await runtime_repo.get(type(op), op.id)
    env = unseal(saved.payload["sealed_env"])
    wheel = Path(__file__).resolve().parents[2] / "bisheng/dev_toolkit/artifacts/bisheng_sdk-0.1.1-py3-none-any.whl"
    sdk = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); from bisheng_sdk import _env; print(_env.platform_api_base())",
            str(wheel),
        ],
        env={key: value for key, value in env.items() if key in {"BISHENG_PLATFORM_API_BASE", "BISHENG_API_BASE_URL"}},
        check=True,
        capture_output=True,
        text=True,
    )
    assert sdk.stdout.strip() == base
    assert env["BISHENG_PLATFORM_API_BASE"] == base
    assert env["APP_CUSTOM_FLAG"] == "kept"
    assert env["BISHENG_APP_STORAGE_ENDPOINT"] == base + f"/api/v1/apps/{op.app_id}/storage"
    assert env["BISHENG_APP_STORAGE_TOKEN"]
    assert env["BISHENG_APP_STORAGE_MAX_FILE_MB"] == str(settings.app_runtime.storage_max_file_mb)
    if preview:
        assert not staged
        assert "BISHENG_APP_TOKEN" not in env and "BISHENG_API_BASE_URL" not in env
        assert "OPENAI_BASE_URL" not in env and "OPENAI_API_KEY" not in env
    else:
        assert staged == [(op.app_id, op.id, ["model:invoke"] if models else [])]
        assert env["BISHENG_API_BASE_URL"] == base and env["BISHENG_APP_TOKEN"] == "fixture-app-token"
        if models:
            assert env["OPENAI_BASE_URL"] == env["BISHENG_MODEL_BASE_URL"] == model_base
            assert env["OPENAI_API_KEY"] == "fixture-app-token"
        else:
            assert "OPENAI_BASE_URL" not in env and "OPENAI_API_KEY" not in env
    await coordinator.inject_environment(op, preview=preview)
    assert (await runtime_repo.get(type(op), op.id)).payload["sealed_env"] == saved.payload["sealed_env"]
