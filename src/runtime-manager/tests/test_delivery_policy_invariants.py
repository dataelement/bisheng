"""F119 覆盖 AC: AC-33, AC-34, AC-35, AC-36, AC-37, AC-40, AC-41: retain existing network/scope policy."""

import pytest


@pytest.mark.parametrize("offline", [False, True])
def test_only_explicit_online_download_may_use_network_and_versions_are_never_changed(tmp_path, offline):
    from runtime_manager.bundle_preparer import BundlePreparer
    from runtime_manager.config import Config
    from tests.test_k8s_helper import package

    original = b'{"dependencies":{"fixture":"1.2.3"}}'
    source = package(
        tmp_path, "input", {"bisheng-app.yaml": b"runtime: node20", "package.json": original, "main.js": b""}
    )
    phases = []

    class Platform:
        def __init__(self):
            self.files = {"source": source}

        def download(self, op, ident, path, **kwargs):
            path.write_bytes(self.files[ident])

        def dependencies(self, *args, **kwargs):
            return {}

        def upload(self, op, archive, *, kind, **kwargs):
            self.files[kind] = archive.read_bytes()
            return {"artifact_id": kind}

    class Runner:
        def cleanup(self, *args):
            pass

        def ensure_image(self, reference, **kwargs):
            return reference

        def run(self, op, phase, **kwargs):
            phases.append((phase, kwargs["network"]))
            mounts = {target: path for path, target, _ in kwargs["mounts"]}
            assert (mounts["/workspace/app"] / "package.json").read_bytes() == original
            if phase == "resolve":
                (mounts["/output"] / "runtime.lock").write_text("fixture==1.2.3")

    profile = {
        "language": "node20",
        "platform": "linux/amd64",
        "profile_id": "node",
        "preparer_image": "preparer",
        "preparer_image_id": "preparer",
        "runtime_image": "runtime",
        "runtime_image_id": "runtime",
        "uid": 10001,
        "gid": 10001,
    }
    op = {
        "operation_id": "op",
        "app_id": "app",
        "payload": {"tenant_id": 3, "source_artifact_id": "source", "profile": profile, "offline": offline},
    }
    platform = Platform()
    preparer = BundlePreparer(
        Config(data_root=tmp_path / "data", build_network="restricted"), platform, runner=Runner()
    )
    result = preparer.prepare(op)
    restored = preparer.restore(op, result)
    assert (restored["code_dir"] / "package.json").read_bytes() == original
    assert phases == ([] if offline else [("download", "restricted")]) + [("resolve", "none"), ("compile", "none")]
    assert op["payload"]["offline"] is offline


def test_private_dependency_identities_remain_app_tenant_and_platform_scoped(tmp_path):
    from runtime_manager.bundle_inputs import dependency_input_key

    (tmp_path / "package.json").write_text('{"dependencies":{"fixture":"1.2.3"}}')
    values = {"tenant_id": 3, "app_id": "app-a", "profile": {"platform": "linux/amd64"}, "language": "node20"}
    key = dependency_input_key(tmp_path, **values)
    for changes in ({"tenant_id": 4}, {"app_id": "app-b"}, {"profile": {"platform": "linux/arm64"}}):
        assert dependency_input_key(tmp_path, **{**values, **changes}) != key
