"""F119 覆盖 AC: AC-28, AC-29, AC-30, AC-31, AC-32: reject before any destructive work."""

from types import SimpleNamespace

import pytest


def test_bundle_missing_runtime_fails_before_source_or_dependency_io(tmp_path):
    from runtime_manager.bundle_preparer import BundlePreparer
    from runtime_manager.config import Config
    from runtime_manager.execution_errors import ExecutionError

    calls = []

    class Runner:
        def ensure_image(self, reference, **kwargs):
            calls.append(reference)
            if reference == "runtime":
                raise ExecutionError("image_missing")
            return reference

        def cleanup(self, *args):
            calls.append("cleanup")

    class Platform:
        def download(self, *args, **kwargs):
            pytest.fail("source download must follow runtime admission")

    profile = {
        "language": "node20",
        "platform": "linux/amd64",
        "runtime_image": "runtime",
        "runtime_image_id": "runtime",
        "preparer_image": "preparer",
        "preparer_image_id": "preparer",
    }
    with pytest.raises(ExecutionError, match="image_missing"):
        BundlePreparer(Config(data_root=tmp_path), Platform(), runner=Runner()).prepare(
            {"operation_id": "op", "app_id": "app", "payload": {"profile": profile}}
        )
    assert "runtime" in calls


def test_missing_frozen_image_does_not_enter_maintenance_or_stop_old_writer(tmp_path, monkeypatch):
    from runtime_manager.config import Config
    from runtime_manager.execution_errors import ExecutionError
    from runtime_manager.operations import OperationExecutor
    from tests.test_operations_v2 import Platform

    platform = Platform("deploy")
    calls = []

    def preflight(operation):
        calls.append("image-check")
        raise ExecutionError("image_missing")

    runtime = SimpleNamespace(preflight=preflight, stop_instances=lambda *args, **kwargs: calls.append("stop"))
    executor = OperationExecutor(Config(data_root=tmp_path), platform, runtime=runtime)
    try:
        monkeypatch.setattr(executor, "_permit", lambda *args: calls.append("permit"))
        with pytest.raises(ExecutionError, match="image_missing"):
            executor._deploy(platform.op)
        assert "stop" not in calls and not platform.facts
        assert "image-check" in calls
    finally:
        executor.close()


def test_legacy_build_uses_the_checked_image_id_even_if_tag_moves(tmp_path, monkeypatch):
    from runtime_manager.bundle_inputs import archive_directory
    from runtime_manager.config import Config
    from runtime_manager.legacy_prepare import prepare_image

    source = tmp_path / "input"
    source.mkdir()
    (source / "bisheng-app.yaml").write_text("runtime: python3.11")
    (source / "main.py").write_text("")
    archive = archive_directory(source, tmp_path / "source.tar.gz").read_bytes()
    checked = "sha256:" + "a" * 64

    class Docker:
        def inspect_image(self, ref):
            return {"Id": checked, "Architecture": "amd64", "Os": "linux"}

        def build_image(self, **kwargs):
            from pathlib import Path

            dockerfile = Path(kwargs["context_dir"]) / "Dockerfile"
            assert "FROM " + checked in dockerfile.read_text()
            yield {"stream": "built"}

    platform = SimpleNamespace(download=lambda op, ident, path, **kw: path.write_bytes(archive))
    op = {
        "operation_id": "op",
        "app_id": "app",
        "payload": {
            "runtime": "python3.11",
            "platform": "linux/amd64",
            "source_artifact_id": "source",
            "offline": True,
        },
    }
    result = prepare_image(
        Config(data_root=tmp_path / "data"),
        platform,
        Docker(),
        op,
        checkpoint=lambda: None,
        report=lambda *args, **kwargs: None,
    )
    assert result["image_id"] == checked


def test_engine_missing_image_reports_the_frozen_role_and_reference(tmp_path):
    from runtime_manager.config import Config
    from runtime_manager.container_runner import ContainerRunner
    from runtime_manager.execution_errors import ExecutionError

    reference = "registry.invalid/runtime@sha256:" + "a" * 64

    class Docker:
        def inspect_image(self, ref):
            raise KeyError(ref)

        def pull_image(self, ref):
            pytest.fail("never policy cannot pull")

    with pytest.raises(ExecutionError, match="image_missing") as caught:
        ContainerRunner(Config(data_root=tmp_path, image_pull_policy="never"), Docker()).ensure_image(
            reference, platform="linux/amd64", role="runtime"
        )
    assert caught.value.image_role == "runtime" and caught.value.image_ref == reference
