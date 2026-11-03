"""F119 覆盖 AC: AC-17, AC-18, AC-19, AC-20: validate and freeze the actual site."""

import io
import tarfile

import pytest


@pytest.mark.parametrize("candidate", [".", "dist", "build", "public"])
def test_uploaded_site_supports_all_directories_without_mutating_source(tmp_path, candidate):
    from runtime_manager.static_inputs import select_static_root

    path = tmp_path / candidate
    path.mkdir(exist_ok=True)
    (path / "index.html").write_text("site")
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert select_static_root(tmp_path, built=False) == path
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before


def test_build_output_wins_only_when_a_build_actually_ran(tmp_path):
    from runtime_manager.static_inputs import select_static_root

    (tmp_path / "index.html").write_text("source")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist/index.html").write_text("compiled")
    assert select_static_root(tmp_path, built=False) == tmp_path
    assert select_static_root(tmp_path, built=True) == tmp_path / "dist"


@pytest.mark.parametrize("escape", ["directory", "index", "internal-link"])
def test_static_links_are_refused(tmp_path, escape):
    from runtime_manager.bundle_inputs import BundleInputError
    from runtime_manager.static_inputs import select_static_root

    root = tmp_path / "source"
    root.mkdir()
    other = tmp_path / "outside"
    other.mkdir()
    (other / "index.html").write_text("outside")
    if escape == "directory":
        (root / "public").symlink_to(other, target_is_directory=True)
    elif escape == "index":
        (root / "index.html").symlink_to(other / "index.html")
    else:
        (root / "actual.html").write_text("inside")
        (root / "index.html").symlink_to(root / "actual.html")
    with pytest.raises(BundleInputError):
        select_static_root(root, built=False)


def test_build_intent_is_read_before_overlays_and_invalid_json_is_a_known_input_error(tmp_path):
    from runtime_manager.bundle_inputs import BundleInputError
    from runtime_manager.static_inputs import has_static_build, select_static_root

    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend/package.json").write_text('{"scripts":{"build":"node build.js"}}')
    assert has_static_build(tmp_path)
    with pytest.raises(BundleInputError, match="static_entry_missing"):
        select_static_root(tmp_path, built=True)
    (tmp_path / "frontend/package.json").write_text("bad json")
    with pytest.raises(BundleInputError, match="package_json_invalid"):
        has_static_build(tmp_path)


@pytest.mark.parametrize("built", [False, True])
@pytest.mark.parametrize("source_image", [False, True])
def test_kubernetes_upload_uses_original_build_intent_and_normalizes_site(tmp_path, built, source_image):
    from runtime_manager.k8s_helper import prepare_download, prepare_upload
    from tests.test_k8s_helper import package, setup

    client, document, _, root = setup.__wrapped__(tmp_path)
    files = {"bisheng-app.yaml": b"runtime: static", "index.html": b"source", "public/index.html": b"site"}
    if built:
        files["package.json"] = b'{"scripts":{"build":"node build.js"}}'
    client.data["source-a"] = package(root, "site", files)
    document["profile"]["language"] = "static"
    document["source_image"] = source_image
    document["delivery"].update(mode="source-image" if source_image else "bundle", startup={})
    work = root / "work"
    prepare_download(client, document, work=work)
    # Build output, then an overlay modifies package.json: selection must use the original marker.
    (work / "source/package.json").write_text("{}")
    (work / "source/dist").mkdir()
    (work / "source/dist/index.html").write_text("compiled")
    (work / "output/runtime.lock").write_text("")
    prepare_upload(client, document, work=work)
    data = next(data for kind, data, *_ in client.uploads if kind == "compiled")
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        assert archive.extractfile("index.html").read() == (b"compiled" if built else b"source")


def test_kubernetes_rejects_missing_output_before_any_artifact_upload(tmp_path):
    from runtime_manager.bundle_inputs import BundleInputError
    from runtime_manager.k8s_helper import prepare_download, prepare_upload
    from tests.test_k8s_helper import package, setup

    client, document, _, root = setup.__wrapped__(tmp_path)
    client.data["source-a"] = package(
        root, "site", {"bisheng-app.yaml": b"runtime: static", "package.json": b'{"scripts":{"build":"node build.js"}}'}
    )
    document["profile"]["language"] = "static"
    work = root / "work"
    prepare_download(client, document, work=work)
    (work / "output/runtime.lock").write_text("")
    with pytest.raises(BundleInputError, match="static_entry_missing"):
        prepare_upload(client, document, work=work)
    assert not client.uploads


@pytest.mark.parametrize("built", [False, True])
@pytest.mark.parametrize("entry", [".", "dist", "build", "public"])
def test_docker_compiled_artifact_and_restore_use_the_selected_site(tmp_path, built, entry):
    from runtime_manager.bundle_preparer import BundlePreparer
    from runtime_manager.config import Config
    from tests.test_k8s_helper import package

    files = {"bisheng-app.yaml": b"runtime: static"}
    if built:
        files["package.json"] = b'{"scripts":{"build":"node build.js"}}'
        # No index exists until compilation completes.
    else:
        files[(entry + "/" if entry != "." else "") + "index.html"] = b"uploaded"
    source_bytes = package(tmp_path, "site-input", files)

    class Platform:
        def __init__(self):
            self.files = {"source": source_bytes}

        def download(self, op, ident, target, **kwargs):
            target.write_bytes(self.files[ident])

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
            mounts = {target: path for path, target, _ in kwargs["mounts"]}
            if phase == "resolve":
                (mounts["/output"] / "runtime.lock").write_text("")
            if phase == "compile" and built:
                site = mounts["/workspace/app"] / entry
                site.mkdir(exist_ok=True)
                (site / "index.html").write_text("compiled")

    profile = {
        "language": "static",
        "platform": "linux/amd64",
        "profile_id": "static",
        "preparer_image": "preparer",
        "preparer_image_id": "preparer",
        "runtime_image": "runtime",
        "runtime_image_id": "runtime",
        "uid": 10001,
        "gid": 10001,
    }
    operation = {
        "operation_id": "op",
        "app_id": "app",
        "payload": {"tenant_id": 1, "source_artifact_id": "source", "profile": profile, "offline": True},
    }
    platform = Platform()
    preparer = BundlePreparer(Config(data_root=tmp_path / "data"), platform, runner=Runner())
    result = preparer.prepare(operation)
    restored = preparer.restore(operation, result)
    assert (restored["code_dir"] / "index.html").read_text() == ("compiled" if built else "uploaded")
