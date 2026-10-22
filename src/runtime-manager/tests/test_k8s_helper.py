"""覆盖 AC: AC-15、AC-16、AC-24、AC-25、AC-26、AC-28、AC-30、AC-34、AC-29、AC-42、AC-43、AC-44、AC-45、AC-46、AC-54."""

import hashlib
import io
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from runtime_manager.bundle_inputs import archive_directory


class Materials:
    def __init__(self):
        self.data = {}
        self.downloads = []
        self.uploads = []

    def describe(self, artifact_id):
        data = self.data[artifact_id]
        return {"artifact_id": artifact_id, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}

    def download(self, artifact_id, destination, *, expected_sha256, expected_size, max_bytes):
        data = self.data[artifact_id]
        assert hashlib.sha256(data).hexdigest() == expected_sha256 and len(data) == expected_size <= max_bytes
        self.downloads.append(artifact_id)
        Path(destination).write_bytes(data)
        return self.describe(artifact_id)

    def upload(self, path, *, kind, platform="", metadata=None):
        self.uploads.append((kind, Path(path).read_bytes(), platform, metadata or {}))
        return {"artifact_id": kind + "-confirmed", "state": "verified", "confirmed_at": "fixture-confirmed"}


def package(tmp_path, name, files):
    root = tmp_path / name
    root.mkdir()
    for relative, data in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return archive_directory(root, tmp_path / (name + ".tar.gz")).read_bytes()


@pytest.fixture
def setup(tmp_path):
    client = Materials()
    client.data["source-a"] = package(
        tmp_path,
        "source",
        {"bisheng-app.yaml": b"runtime: python3.11\n", "main.py": b"print('application')\n", "requirements.txt": b""},
    )
    client.data["compiled-a"] = package(tmp_path, "compiled", {"main.py": b"print('compiled')\n"})
    client.data["dependencies-a"] = package(
        tmp_path,
        "dependencies",
        {"runtime.lock": b"fixture==1 --hash=sha256:" + b"a" * 64 + b"\n", "wheels/fixture.whl": b"wheel"},
    )
    profile = {
        "profile_id": "python-1",
        "profile_digest": "a" * 64,
        "language": "python3.11",
        "platform": "linux/amd64",
        "abi": "cpython-311-glibc",
        "runtime_image_id": "sha256:" + "b" * 64,
    }
    document = {
        "tenant_id": 1,
        "app_id": "app-a",
        "source_artifact_id": "source-a",
        "profile": profile,
        "delivery": {"dependencies": {}, "startup": {"command": ["python", "main.py"]}},
        "phase": "inputs",
    }
    delivery = {
        "mode": "bundle",
        "profile": profile,
        "compiled_artifact_id": "compiled-a",
        "dependency_artifact_id": "dependencies-a",
        "environment_key": "c" * 64,
    }
    return client, document, delivery, tmp_path


def test_runtime_fetch_only_validates_and_extracts_frozen_artifacts(setup, monkeypatch):
    from runtime_manager.k8s_helper import fetch_runtime

    client, _, delivery, root = setup
    monkeypatch.setattr(
        "subprocess.run", lambda *args, **kwargs: pytest.fail("trusted material fetch must not run application code")
    )
    fetch_runtime(client, delivery, code=root / "code", materials=root / "materials", tools=root / "tools")
    assert (root / "code/main.py").read_bytes() == b"print('compiled')\n"
    script = (root / "tools/environment.sh").read_text()
    assert "/opt/venv" in script and "--no-index" in script and "--require-hashes" in script
    assert "-I -m pip" in script and "import bisheng_sdk" in script
    assert client.downloads == ["compiled-a", "dependencies-a"]


@pytest.mark.parametrize("language", ["node20", "static"])
def test_non_python_environment_does_not_require_python_in_runtime_image(setup, language):
    from runtime_manager.k8s_helper import fetch_runtime

    client, _, delivery, root = setup
    delivery["profile"] = {**delivery["profile"], "language": language}
    fetch_runtime(client, delivery, code=root / "code", materials=root / "materials", tools=root / "tools")
    assert "python" not in (root / "tools/environment.sh").read_text().lower()


def test_malicious_material_cannot_escape_the_mount(setup):
    from runtime_manager.k8s_helper import fetch_runtime

    client, _, delivery, root = setup
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tar:
        entry = tarfile.TarInfo("../outside")
        entry.size = 3
        tar.addfile(entry, io.BytesIO(b"bad"))
    client.data["compiled-a"] = data.getvalue()
    with pytest.raises(ValueError):
        fetch_runtime(client, delivery, code=root / "code", materials=root / "materials", tools=root / "tools")
    assert not (root / "outside").exists()


def test_data_layout_keeps_private_backups_separate_and_rejects_symlinks(tmp_path):
    from runtime_manager.k8s_helper import initialize_data_layout

    volume = tmp_path / "volume"
    initialize_data_layout(volume)
    assert (
        (volume / "business").is_dir()
        and (volume / "platform/backups").is_dir()
        and (volume / "platform/journal").is_dir()
    )
    shutil.rmtree(volume / "platform")
    (volume / "platform").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        initialize_data_layout(volume)


def test_first_download_phase_computes_inputs_without_installing_or_fetching_packages(setup):
    from runtime_manager.k8s_helper import prepare_download

    client, document, _, root = setup
    result = prepare_download(
        client,
        document,
        work=root / "work",
        resolver=lambda *args: pytest.fail("inputs phase must not resolve dependencies"),
    )
    assert len(result["input_key"]) == 64 and client.downloads == ["source-a"]
    assert (root / "work/original/main.py").is_file() and (root / "work/source/main.py").is_file()
    assert (root / "work/tools/k8s_prepare.py").is_file()


def test_cached_dependencies_are_downloaded_without_install_or_registry_access(setup):
    from runtime_manager.k8s_helper import prepare_download

    client, document, _, root = setup
    first = prepare_download(client, document, work=root / "work")
    document = {
        **document,
        "phase": "resolve",
        "dependency_resolution": {
            "input_key": first["input_key"],
            "artifact_id": "dependencies-a",
            "state": "verified",
        },
    }
    result = prepare_download(
        client, document, work=root / "work", resolver=lambda *args: pytest.fail("cache hit must not resolve")
    )
    assert result["cached"] is True and (root / "work/materials/runtime.lock").is_file()
    assert json.loads((root / "work/tools/prepare.json").read_text())["cached"] is True


def test_cache_selection_cannot_reuse_material_for_different_inputs(setup):
    from runtime_manager.k8s_helper import prepare_download

    client, document, _, root = setup
    prepare_download(client, document, work=root / "work")
    document = {
        **document,
        "phase": "resolve",
        "dependency_resolution": {"input_key": "f" * 64, "artifact_id": "dependencies-a", "state": "verified"},
    }
    with pytest.raises(ValueError):
        prepare_download(client, document, work=root / "work")


def test_new_inputs_resolve_only_in_trusted_download_phase(setup):
    from runtime_manager.k8s_helper import prepare_download

    client, document, _, root = setup
    first = prepare_download(client, document, work=root / "work")
    calls = []

    def resolver(document, source, offline, output):
        calls.append(source)
        output.mkdir()
        (output / "runtime.lock").write_text("")
        (output / "wheels").mkdir()

    document = {
        **document,
        "phase": "resolve",
        "dependency_resolution": {"input_key": first["input_key"], "artifact_id": None, "state": "claimed"},
    }
    result = prepare_download(client, document, work=root / "work", resolver=resolver)
    assert not result["cached"] and len(calls) == 1
    assert (root / "work/materials/runtime.lock").is_file()


def test_environment_input_key_includes_profile_abi_architecture_and_application(setup):
    from runtime_manager.k8s_helper import prepare_download

    client, document, _, root = setup
    keys = []
    for index, change in enumerate(
        (
            {},
            {"profile": {**document["profile"], "abi": "other-abi"}},
            {"profile": {**document["profile"], "platform": "linux/arm64"}},
            {"app_id": "app-b"},
        )
    ):
        keys.append(prepare_download(client, {**document, **change}, work=root / str(index))["input_key"])
    assert len(set(keys)) == 4


def test_upload_reads_data_only_and_returns_verified_delivery_references(setup, monkeypatch):
    from runtime_manager.k8s_helper import prepare_download, prepare_upload

    client, document, _, root = setup
    prepare_download(client, document, work=root / "work")
    (root / "work/output/runtime.lock").write_text("")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: pytest.fail("trusted uploader must not execute code"))
    result = prepare_upload(client, document, work=root / "work")
    assert (
        result["compiled_artifact_id"] == "compiled-confirmed"
        and result["dependency_artifact_id"] == "dependencies-confirmed"
    )
    assert result["startup"]["command"] == ["python", "main.py"]
    assert [x[0] for x in client.uploads] == ["dependencies", "compiled"]


def test_upload_rejects_a_symlink_outside_the_scratch_volume(setup):
    from runtime_manager.k8s_helper import prepare_download, prepare_upload

    client, document, _, root = setup
    prepare_download(client, document, work=root / "work")
    (root / "work/output/runtime.lock").write_text("")
    (root / "work/source/escape").symlink_to(root / "outside")
    (root / "outside").write_text("fixture private")
    with pytest.raises(ValueError):
        prepare_upload(client, document, work=root / "work")


def test_standalone_install_uses_cached_overlay_without_repeating_install_hooks(tmp_path):
    from runtime_manager.k8s_prepare import prepare

    source, original, materials, output = [tmp_path / x for x in ("source", "original", "materials", "output")]
    for path in (source, original, materials, output):
        path.mkdir()
    (materials / "install-overlay").mkdir()
    (materials / "install-overlay/generated.py").write_text("fixture generated")
    (materials / "install-deleted.json").write_text('["remove.py"]')
    (source / "remove.py").write_text("remove")
    calls = []

    class Common:
        def lock(self, language):
            pytest.fail("cached dependency install must not repeat")

        def build(self, language):
            calls.append(language)

    prepare(
        {"language": "python3.11", "cached": True},
        source=source,
        original=original,
        materials=materials,
        output=output,
        common=Common(),
    )
    assert (source / "generated.py").read_text() == "fixture generated" and not (source / "remove.py").exists()
    assert calls == ["python3.11"]


def test_new_install_materials_are_used_for_build_without_transmission_identity(tmp_path):
    from runtime_manager.k8s_prepare import prepare

    calls = []

    class Common:
        def lock(self, language):
            calls.append("lock")

        def build(self, language):
            assert self.MATERIALS == tmp_path / "output"
            calls.append("build")

    prepare(
        {"language": "node20", "cached": False},
        source=tmp_path / "source",
        original=tmp_path / "original",
        materials=tmp_path / "materials",
        output=tmp_path / "output",
        common=Common(),
    )
    assert calls == ["lock", "build"]


def test_trusted_resolver_isolates_python_package_download_from_source_imports(setup, monkeypatch):
    from runtime_manager import k8s_helper as helper

    _client, document, _, root = setup
    calls = []

    class Tool:
        def download(self, language):
            self.run("python", "-m", "pip", "download", "--only-binary=:all:")

    monkeypatch.setattr(helper, "_load_download_tool", lambda: Tool())
    monkeypatch.setattr(helper.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))
    helper.resolve_download(document, root / "source", root / "offline", root / "output")
    assert calls[0][0][:4] == ["python", "-I", "-m", "pip"]
    assert calls[0][1]["cwd"] == root / "source"


def test_private_identity_uses_pod_uid_from_downward_api_and_fresh_bounded_init_deadline(tmp_path, monkeypatch):
    from runtime_manager import k8s_helper as helper

    captured = {}

    class Client:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(helper, "MaterialClient", Client)
    monkeypatch.setenv("MATERIAL_POD_UID", "22222222-2222-4222-8222-222222222222")
    identity = {
        "base_url": "https://backend",
        "delegation_id": "11111111-1111-4111-8111-111111111111",
        "key_id": "init-key",
        "private_key": "01" * 32,
        "scope_kind": "deployment-init",
        "expires_at": None,
        "phase_timeout_seconds": 300,
    }
    path = tmp_path / "identity.json"
    path.write_text(json.dumps(identity))
    helper.client_from_identity(path, clock=lambda: 100000)
    assert captured["pod_uid"] == "22222222-2222-4222-8222-222222222222" and captured["deadline"] == 100300
    identity.update(scope_kind="operation", expires_at=100030)
    path.write_text(json.dumps(identity))
    helper.client_from_identity(path, clock=lambda: 100000)
    assert captured["deadline"] == 100030


def test_unknown_or_nonfinite_identity_scope_is_refused(tmp_path, monkeypatch):
    from runtime_manager import k8s_helper as helper

    monkeypatch.setenv("MATERIAL_POD_UID", "22222222-2222-4222-8222-222222222222")
    identity = {
        "base_url": "https://backend",
        "delegation_id": "11111111-1111-4111-8111-111111111111",
        "key_id": "init-key",
        "private_key": "01" * 32,
        "scope_kind": "unexpected",
        "expires_at": float("nan"),
    }
    path = tmp_path / "identity.json"
    path.write_text(json.dumps(identity))
    with pytest.raises(ValueError):
        helper.client_from_identity(path, clock=lambda: 100000)


def test_material_binding_wait_is_bounded_and_does_not_extend_phase_deadline(setup):
    from runtime_manager import k8s_helper as helper
    from runtime_manager.material_client import MaterialClientError

    client, _, delivery, root = setup
    original = client.describe
    attempts = []
    client.clock = lambda: 100000
    client.deadline = 100060
    client.sleep = lambda _: None

    def describe(artifact_id):
        attempts.append(artifact_id)
        if len(attempts) == 1:
            raise MaterialClientError("material_request_refused", 409)
        return original(artifact_id)

    client.describe = describe
    helper.fetch_runtime(client, delivery, code=root / "code", materials=root / "materials", tools=root / "tools")
    assert attempts[:2] == ["compiled-a", "compiled-a"]
    assert len(attempts) == 5 and client.deadline == 100060


def test_binding_wait_stops_at_the_original_deadline():
    from runtime_manager import k8s_helper as helper
    from runtime_manager.material_client import MaterialClientError

    state = {"now": 100000, "attempts": 0}

    class Client:
        deadline = 100002

        def clock(self):
            return state["now"]

        def sleep(self, seconds):
            state["now"] += seconds

        def describe(self, artifact_id):
            state["attempts"] += 1
            raise MaterialClientError("material_request_refused", 409)

    with pytest.raises(MaterialClientError):
        helper._manifest(Client(), "compiled-a")
    assert state["now"] <= 100002 and state["attempts"] <= 6


def guard_document():
    return {
        "namespace": "runtime-apps",
        "installation_id": "e2e-f059",
        "filesystem": "ext4",
        "capacity_bytes": 1024**3,
        "marker_required": True,
    }


def test_verify_volume_is_readonly_and_never_creates_business_layout(tmp_path, monkeypatch):
    from runtime_manager import k8s_capabilities
    from runtime_manager.k8s_helper import verify_volume

    marker = tmp_path / ".bisheng-volume.json"
    marker.write_text(json.dumps({"namespace": "runtime-apps", "installation_id": "e2e-f059"}))
    monkeypatch.setattr(k8s_capabilities, "mounted_filesystem", lambda path: "ext4")
    monkeypatch.setattr(k8s_capabilities, "volume_capacity", lambda path: 1024**3)
    before = marker.read_bytes()
    assert verify_volume(tmp_path, guard=guard_document()) == {"verified": True}
    assert marker.read_bytes() == before
    assert sorted(path.name for path in tmp_path.iterdir()) == [".bisheng-volume.json"]


@pytest.mark.parametrize(
    "problem", ["unmounted", "oversized", "undersized", "marker-missing", "wrong-scope", "unknown-filesystem"]
)
def test_bad_scratch_volume_is_rejected_without_writes(tmp_path, monkeypatch, problem):
    from runtime_manager import k8s_capabilities
    from runtime_manager.k8s_helper import initialize_data_layout, verify_volume

    marker = tmp_path / ".bisheng-volume.json"
    marker.write_text(
        json.dumps(
            {"namespace": "other-apps" if problem == "wrong-scope" else "runtime-apps", "installation_id": "e2e-f059"}
        )
    )
    if problem == "marker-missing":
        marker.unlink()
    filesystem = "overlay" if problem == "unmounted" else "" if problem == "unknown-filesystem" else "ext4"
    capacity = 500 * 1024**3 if problem == "oversized" else 128 * 1024**2 if problem == "undersized" else 1024**3
    monkeypatch.setattr(k8s_capabilities, "mounted_filesystem", lambda path: filesystem)
    monkeypatch.setattr(k8s_capabilities, "volume_capacity", lambda path: capacity)
    for action in (verify_volume, initialize_data_layout):
        with pytest.raises(ValueError, match="volume_"):
            action(tmp_path, guard=guard_document())
    assert not (tmp_path / "business").exists() and not (tmp_path / "platform").exists()


def test_guard_does_not_create_missing_volume_or_accept_a_symlink(tmp_path):
    from runtime_manager.k8s_helper import verify_volume

    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="volume_"):
        verify_volume(missing, guard=guard_document())
    assert not missing.exists()
    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="volume_"):
        verify_volume(linked, guard=guard_document())


def test_storage_guard_cli_never_constructs_download_identity_or_runs_source(monkeypatch):
    from runtime_manager import k8s_helper

    monkeypatch.setattr(k8s_helper.sys, "argv", ["helper", "storage-guard"])
    monkeypatch.setenv("VOLUME_GUARD", json.dumps(guard_document()))
    monkeypatch.setattr(
        k8s_helper, "client_from_identity", lambda: pytest.fail("guard must not load material identity")
    )
    monkeypatch.setattr(
        k8s_helper, "prepare_download", lambda *args, **kwargs: pytest.fail("guard must not download source")
    )
    seen = []
    monkeypatch.setattr(k8s_helper, "verify_volume", lambda **kwargs: seen.append(kwargs) or {"verified": True})
    k8s_helper.main()
    assert seen == [{"guard": guard_document()}]
    monkeypatch.setattr(
        k8s_helper, "verify_volume", lambda **kwargs: (_ for _ in ()).throw(ValueError("volume_capacity_unbounded"))
    )
    with pytest.raises(ValueError, match="volume_capacity"):
        k8s_helper.main()


@pytest.mark.parametrize(
    "declared", [None, ["nginx", "-g", "daemon off;", "-q"], ["/bin/sh", "-c", "exec /custom-server"]]
)
def test_static_upload_freezes_startup_argv_without_baking_in_runtime_wrapper(setup, declared, monkeypatch):
    from runtime_manager.k8s_helper import prepare_download, prepare_upload

    client, document, _, root = setup
    client.data["source-a"] = package(
        root, "static-source", {"bisheng-app.yaml": b"runtime: static\n", "index.html": b"<h1>default static</h1>"}
    )
    document["profile"]["language"] = "static"
    document["delivery"]["startup"] = {} if declared is None else {"command": declared}
    prepare_download(client, document, work=root / "work")
    (root / "work/output/runtime.lock").write_text("")
    monkeypatch.setattr(
        "subprocess.run", lambda *args, **kwargs: pytest.fail("static trusted upload must never run source")
    )
    result = prepare_upload(client, document, work=root / "work")
    assert result["startup"]["command"] == (declared or ["nginx", "-g", "daemon off;"])
    assert result["profile"]["language"] == "static"
    assert "/opt/bisheng/entrypoint.sh" not in result["startup"]["command"]
    assert document["delivery"]["startup"] == ({} if declared is None else {"command": declared})
    compiled = next(payload for kind, payload, _platform, _metadata in client.uploads if kind == "compiled")
    with tarfile.open(fileobj=io.BytesIO(compiled)) as archive:
        assert archive.extractfile("index.html").read() == b"<h1>default static</h1>"
