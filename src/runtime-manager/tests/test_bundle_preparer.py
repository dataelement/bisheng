"""Dependency identities exclude plain source changes but include installation inputs."""

import io
import tarfile

import pytest


def test_python_code_reuses_dependencies_but_abi_does_not(tmp_path):
    """AC-20, AC-21, AC-24: reuse is scoped and sensitive to runtime compatibility."""
    from runtime_manager.bundle_inputs import dependency_input_key

    (tmp_path / "requirements.txt").write_text("httpx==0.27.0\n")
    (tmp_path / "main.py").write_text("print(1)")
    args = {"tenant_id": 1, "app_id": "app-a", "profile": {"abi": "cp311", "image_id": "a"}, "language": "python3.11"}
    first = dependency_input_key(tmp_path, **args)
    (tmp_path / "main.py").write_text("print(2)")
    assert dependency_input_key(tmp_path, **args) == first
    assert dependency_input_key(tmp_path, **{**args, "tenant_id": 2}) != first
    assert dependency_input_key(tmp_path, **{**args, "profile": {"abi": "cp312", "image_id": "b"}}) != first


def test_node_source_hook_invalidates_reuse(tmp_path):
    """AC-25: postinstall inputs cannot share a stale source-dependent environment."""
    from runtime_manager.bundle_inputs import dependency_input_key

    (tmp_path / "package.json").write_text('{"scripts":{"postinstall":"node generate.js"}}')
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{}}')
    script = tmp_path / "generate.js"
    script.write_text("first")
    args = {"tenant_id": 1, "app_id": "app-a", "profile": {}, "language": "node20"}
    first = dependency_input_key(tmp_path, **args)
    script.write_text("second")
    assert dependency_input_key(tmp_path, **args) != first


@pytest.mark.parametrize("name,link", [("../escape", None), ("/absolute", None), ("symlink", "../../escape")])
def test_archive_escape_is_rejected(tmp_path, name, link):
    """AC-07: source and dependency archives cannot write outside their root."""
    from runtime_manager.bundle_inputs import BundleInputError, extract_archive

    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as output:
        info = tarfile.TarInfo(name)
        if link:
            info.type = tarfile.SYMTYPE
            info.linkname = link
            output.addfile(info)
        else:
            info.size = 1
            output.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(BundleInputError):
        extract_archive(archive, tmp_path / "output", internal_links=True)
    assert not (tmp_path / "escape").exists()


def test_reproducible_archive_and_bounded_extraction(tmp_path):
    """AC-07, AC-19, AC-36: immutable content is reproducible and size checked."""
    from runtime_manager.bundle_inputs import BundleInputError, archive_directory, extract_archive

    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("print(1)")
    a = archive_directory(source, tmp_path / "a.tar.gz")
    b = archive_directory(source, tmp_path / "b.tar.gz")
    assert a.read_bytes() == b.read_bytes()
    with pytest.raises(BundleInputError):
        extract_archive(a, tmp_path / "output", max_bytes=1)


def test_code_only_release_reuses_frozen_materials_and_venv(tmp_path):
    """AC-19, AC-20, AC-22, AC-23: reuse keeps new source and never repeats resolution."""
    from runtime_manager.bundle_inputs import archive_directory
    from runtime_manager.bundle_preparer import BundlePreparer
    from runtime_manager.config import Config
    from runtime_manager.platform_protocol import content_digest

    class Platform:
        def __init__(self):
            self.files = {}
            self.plans = {}

        def download(self, op, ident, path, **kwargs):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.files[ident])

        def upload(self, op, path, **kwargs):
            ident = content_digest({"bytes": path.read_bytes().hex()})
            self.files[ident] = path.read_bytes()
            return {"artifact_id": ident}

        def dependencies(self, op, key, *, artifact_id=None, verified=False):
            if artifact_id:
                self.plans[key] = artifact_id
            return {"artifact_id": self.plans.get(key)}

    class Runner:
        def __init__(self):
            self.phases = []

        def ensure_image(self, reference, **kwargs):
            return kwargs["expected_id"]

        def cleanup(self, op):
            return True

        def reset_phase(self, op, phase):
            return None

        def run(self, op, phase, **kwargs):
            self.phases.append(phase)
            mounts = {target: path for path, target, _ in kwargs["mounts"]}
            if phase == "resolve":
                (mounts["/output"] / "runtime.lock").write_text("")
            if phase == "materialize":
                (mounts["/opt/venv"] / "installed").write_text("immutable-dependencies")

    profile = {
        "language": "python3.11",
        "platform": "linux/arm64",
        "profile_id": "profile-a",
        "runtime_image": "image@sha256:" + "a" * 64,
        "runtime_image_id": "sha256:" + "a" * 64,
        "preparer_image": "image@sha256:" + "b" * 64,
        "preparer_image_id": "sha256:" + "b" * 64,
        "uid": 10001,
        "gid": 10001,
        "abi": "cp311",
    }
    platform = Platform()
    runner = Runner()
    config = Config(data_root=tmp_path / "data")
    preparer = BundlePreparer(config, platform, runner=runner)
    source = tmp_path / "source"
    source.mkdir()
    (source / "bisheng-app.yaml").write_text("manifest_version: 2")
    (source / "requirements.txt").write_text("")
    results = []
    for n in [1, 2]:
        (source / "main.py").write_text(f"print({n})")
        archive = archive_directory(source, tmp_path / f"source-{n}.tar.gz")
        platform.files[f"source-{n}"] = archive.read_bytes()
        op = {
            "operation_id": f"op-{n}",
            "app_id": "app-a",
            "version_id": f"v-{n}",
            "generation": n,
            "owner_epoch": 1,
            "payload": {
                "tenant_id": 1,
                "source_artifact_id": f"source-{n}",
                "profile": profile,
                "offline": True,
                "delivery": {"startup": {"command": ["python", "main.py"]}},
            },
        }
        delivery = preparer.prepare(op)
        restored = preparer.restore(op, delivery)
        assert (restored["code_dir"] / "main.py").read_text() == f"print({n})"
        results.append(delivery)
    assert results[0]["dependency_artifact_id"] == results[1]["dependency_artifact_id"]
    assert results[0]["compiled_artifact_id"] != results[1]["compiled_artifact_id"]
    assert runner.phases.count("resolve") == 1
    assert runner.phases.count("materialize") == 1
    assert runner.phases.count("compile") == 2


def preparation_script():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "preparation_script", Path(__file__).parents[2] / "app-runtime/common/prepare.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "requirement",
    [
        "danger @ https://example/danger.tar.gz",
        "git+https://example/repo",
        "--index-url https://example",
        "-r ../outside.txt",
    ],
)
def test_downloader_refuses_executable_or_escaped_dependency_inputs(tmp_path, monkeypatch, requirement):
    helper = preparation_script()
    monkeypatch.setattr(helper, "SOURCE", tmp_path)
    path = tmp_path / "requirements.txt"
    path.write_text(requirement)
    with pytest.raises(RuntimeError):
        helper.requirement_lines(path)


def test_requirement_includes_and_constraints_are_preserved(tmp_path, monkeypatch):
    helper = preparation_script()
    monkeypatch.setattr(helper, "SOURCE", tmp_path)
    monkeypatch.setattr(helper, "OUTPUT", tmp_path)
    (tmp_path / "constraints.txt").write_text("httpx<0.29\n")
    (tmp_path / "nested.txt").write_text("httpx>=0.28\n")
    req = tmp_path / "requirements.txt"
    req.write_text("-r nested.txt\n-c constraints.txt\n")
    result = helper.safe_requirements(req, tmp_path / "download.in").read_text()
    assert "httpx>=0.28" in result and "-c " in result
    assert (tmp_path / "download.in.constraints").read_text() == "httpx<0.29\n"


def test_nested_requirement_changes_invalidate_environment(tmp_path):
    from runtime_manager.bundle_inputs import dependency_input_key

    (tmp_path / "requirements.txt").write_text("-r nested.txt\n")
    nested = tmp_path / "nested.txt"
    nested.write_text("httpx==0.28.0")
    args = {"tenant_id": 1, "app_id": "app", "profile": {}, "language": "python3.11"}
    first = dependency_input_key(tmp_path, **args)
    nested.write_text("httpx==0.28.1")
    assert dependency_input_key(tmp_path, **args) != first
