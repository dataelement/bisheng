"""Runtime payloads bind immutable code/dependencies and never publish host ports."""

from pathlib import Path

import pytest


class Images:
    def inspect_image(self, reference):
        return {"Id": "sha256:" + "a" * 64, "Os": "linux", "Architecture": "arm64"}


def operation():
    return {
        "operation_id": "operation-a",
        "app_id": "app-a",
        "version_id": "version-a",
        "generation": 1,
        "owner_epoch": 1,
        "payload": {"slug": "example", "port": 8080, "tier": {"memory_mb": 512, "cpu_millicores": 500}},
    }


def test_bundle_paths_use_host_frame_and_read_only_inputs(tmp_path):
    """AC-11, AC-18, AC-22, AC-46, AC-52: internal port reuse does not expose the host."""
    from runtime_manager.bundle_launch import BundleLauncher
    from runtime_manager.config import Config

    config = Config(data_root=tmp_path, host_data_root=Path("/host/data"))
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("")
    env = tmp_path / "env"
    env.mkdir()
    delivery = {
        "mode": "bundle",
        "profile": {
            "language": "python3.11",
            "platform": "linux/arm64",
            "runtime_image": "example@sha256:" + "a" * 64,
            "runtime_image_id": "sha256:" + "a" * 64,
        },
        "startup": {"command": ["uvicorn", "main:app"]},
    }
    payload = BundleLauncher(config, Images()).payload(operation(), delivery, code_dir=source, environment_dir=env)
    assert payload["HostConfig"]["PortBindings"] == {}
    assert "/host/data/source:/workspace/app:ro" in payload["HostConfig"]["Binds"]
    assert "/host/data/env:/opt/venv:ro" in payload["HostConfig"]["Binds"]
    assert payload["HostConfig"]["CapDrop"] == ["ALL"]
    assert payload["HostConfig"]["ReadonlyRootfs"] is True
    assert payload["User"] == "10001:10001"


def test_wrong_architecture_or_control_environment_is_rejected(tmp_path):
    """AC-31, AC-53, AC-56: preloading an incompatible image does not count as ready."""
    from runtime_manager.bundle_inputs import BundleInputError
    from runtime_manager.bundle_launch import BundleLauncher
    from runtime_manager.config import Config
    from runtime_manager.container_runner import ContainerRunner, ExecutionError

    runner = ContainerRunner(Config(data_root=tmp_path), Images())
    with pytest.raises(ExecutionError, match="platform"):
        runner.ensure_image("sha256:" + "a" * 64, platform="linux/amd64", expected_id="sha256:" + "a" * 64)
    op = operation()
    op["payload"]["runtime_env"] = {"RTM_HMAC_SECRET": "fixture-not-allowed"}
    delivery = {"mode": "image", "image_ref": "sha256:" + "a" * 64, "platform": "linux/arm64"}
    with pytest.raises(BundleInputError, match="control"):
        BundleLauncher(Config(data_root=tmp_path), Images()).payload(op, delivery)
