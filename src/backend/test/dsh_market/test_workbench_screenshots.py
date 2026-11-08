"""Declared screenshot import, distribution and tenant/account API stories."""

import hashlib
import io
import json
import tarfile

import httpx
import pytest
from PIL import Image

from bisheng.dsh_market.api.auth import MarketActor, market_actor
from bisheng.dsh_market.domain.workbench_bundle import WorkbenchBundleError, validate_workbench_bundle
from bisheng.dsh_market.domain.workbench_service import WorkbenchArtifactError
from test.dsh_market import test_desktop_auth as desktop_fixtures
from test.dsh_market import test_workbench as workbench_fixtures
from test.dsh_market.test_workbench import archive

service = workbench_fixtures.service
workbench_client = workbench_fixtures.workbench_client
market_app = desktop_fixtures.market_app


ROOT = "/api/v1/dsh/market"


def image_bytes(fmt="PNG", size=(64, 32), color="navy", **options):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format=fmt, **options)
    return output.getvalue()


def screenshot_archive(declarations=None, images=None, version="1.0.0", workbench=None, **kwargs):
    """Repack a synthetic fixture; no source execution and no third-party archive mutation."""
    original = archive(version, **kwargs)
    with tarfile.open(fileobj=io.BytesIO(original), mode="r:gz") as tar:
        files = {item.name: tar.extractfile(item).read() for item in tar if item.isfile()}
    package = json.loads(files["package/package.json"])
    package["dsh"]["workbench"] = (
        workbench
        if workbench is not None
        else {
            "screenshots": declarations
            if declarations is not None
            else [{"path": "./assets/overview.png", "alt": "工作台概览"}]
        }
    )
    files["package/package.json"] = json.dumps(package).encode()
    files.update(images if images is not None else {"package/assets/overview.png": image_bytes()})
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        for path, raw in files.items():
            item = tarfile.TarInfo(path)
            item.size = len(raw)
            tar.addfile(item, io.BytesIO(raw))
    return output.getvalue()


@pytest.mark.parametrize(
    ("fmt", "extension", "media_type"),
    [
        ("PNG", "png", "image/png"),
        ("JPEG", "jpg", "image/jpeg"),
        ("JPEG", "jpeg", "image/jpeg"),
        ("WEBP", "webp", "image/webp"),
    ],
)
def test_real_static_image_formats(fmt, extension, media_type):
    raw = image_bytes(fmt)
    data = screenshot_archive([{"path": "assets/shot." + extension}], {"package/assets/shot." + extension: raw})
    image = validate_workbench_bundle(data)["screenshots"][0]
    assert image["media_type"] == media_type
    assert (image["width"], image["height"], image["bytes"]) == (64, 32, len(raw))
    assert image["sha256"] == hashlib.sha256(raw).hexdigest()
    assert image["alt"] == ""


@pytest.mark.parametrize(
    "declarations",
    [
        None,
        "assets/overview.png",
        {},
        ["assets/overview.png"],
        [{}],
        [{"url": "https://example.org/a.png"}],
        [{"path": "assets/overview.png", "unknown": True}],
        [{"path": "assets/overview.png", "alt": None}],
        [{"path": "assets/overview.png", "alt": "a" * 257}],
        [{"path": "assets/overview.png", "alt": "bad\nalt"}],
        [{"path": "assets/overview.png"}, {"path": "./assets/overview.png"}],
    ],
)
def test_invalid_declarations_rejected(declarations):
    data = screenshot_archive(workbench={"screenshots": declarations})
    with pytest.raises(WorkbenchBundleError) as caught:
        validate_workbench_bundle(data)
    assert caught.value.code == "WORKBENCH_SCREENSHOT_DECLARATION"
    assert caught.value.field.startswith("dsh.workbench.screenshots")


@pytest.mark.parametrize(
    "path",
    [
        "../a.png",
        "/assets/overview.png",
        "https://example.org/a.png",
        "file:///tmp/a.png",
        "assets/../overview.png",
        "assets//overview.png",
        "assets\\overview.png",
        "assets/%2e%2e/a.png",
        "assets/overview.png?x=1",
        "assets/overview.png#foo",
        "assets/\x00a.png",
        "",
        1,
    ],
)
def test_unsafe_declared_paths_rejected(path):
    with pytest.raises(WorkbenchBundleError) as caught:
        validate_workbench_bundle(screenshot_archive([{"path": path}]))
    assert caught.value.code == "WORKBENCH_SCREENSHOT_PATH"


@pytest.mark.parametrize("workbench", [[], "invalid", False])
def test_invalid_workbench_namespace_rejected(workbench):
    with pytest.raises(WorkbenchBundleError, match="Workbench declaration"):
        validate_workbench_bundle(screenshot_archive(workbench=workbench))


def test_missing_and_undeclared_images():
    with pytest.raises(WorkbenchBundleError) as caught:
        validate_workbench_bundle(screenshot_archive(images={}))
    assert caught.value.code == "WORKBENCH_SCREENSHOT_MISSING"
    # Neither scanning all pictures nor a workbench namespace without screenshots opts in.
    assert validate_workbench_bundle(archive(extra={"package/assets/unlisted.png": image_bytes()}))["screenshots"] == []
    assert validate_workbench_bundle(screenshot_archive(workbench={}))["screenshots"] == []
    assert validate_workbench_bundle(screenshot_archive([]))["screenshots"] == []


@pytest.mark.parametrize("raw", [b"not an image", b"<svg xmlns='http://www.w3.org/2000/svg'/>", image_bytes()[:-15]])
def test_fake_or_truncated_png_rejected(raw):
    with pytest.raises(WorkbenchBundleError) as caught:
        validate_workbench_bundle(screenshot_archive(images={"package/assets/overview.png": raw}))
    assert caught.value.code == "WORKBENCH_SCREENSHOT_IMAGE"


def test_type_mismatch_svg_and_animation_rejected():
    with pytest.raises(WorkbenchBundleError) as caught:
        validate_workbench_bundle(screenshot_archive(images={"package/assets/overview.png": image_bytes("JPEG")}))
    assert caught.value.code == "WORKBENCH_SCREENSHOT_TYPE"
    with pytest.raises(WorkbenchBundleError, match="Only PNG, JPEG and WebP"):
        validate_workbench_bundle(
            screenshot_archive([{"path": "assets/shot.svg"}], {"package/assets/shot.svg": b"<svg/>"})
        )
    output = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(
        output, format="PNG", save_all=True, append_images=[Image.new("RGB", (32, 32), "blue")]
    )
    with pytest.raises(WorkbenchBundleError, match="Animated"):
        validate_workbench_bundle(screenshot_archive(images={"package/assets/overview.png": output.getvalue()}))


def test_count_byte_and_pixel_limits():
    with pytest.raises(WorkbenchBundleError, match="At most 8"):
        validate_workbench_bundle(screenshot_archive([{"path": f"assets/{index}.png"} for index in range(9)]))
    raw = image_bytes()
    # Actual archive members at/above the bound, no threshold monkeypatch.
    boundary = raw + b"\0" * (5 * 1024 * 1024 - len(raw))
    assert validate_workbench_bundle(screenshot_archive(images={"package/assets/overview.png": boundary}))[
        "screenshots"
    ][0]["bytes"] == len(boundary)
    with pytest.raises(WorkbenchBundleError, match="5 MiB"):
        validate_workbench_bundle(screenshot_archive(images={"package/assets/overview.png": boundary + b"\0"}))
    with pytest.raises(WorkbenchBundleError, match="20 MiB"):
        validate_workbench_bundle(
            screenshot_archive(
                [{"path": f"assets/{index}.png"} for index in range(5)],
                {f"package/assets/{index}.png": boundary for index in range(5)},
            )
        )
    for size in [(8193, 1), (4001, 4000)]:
        with pytest.raises(WorkbenchBundleError, match="16 megapixels"):
            validate_workbench_bundle(
                screenshot_archive(images={"package/assets/overview.png": image_bytes(size=size)})
            )


def test_image_import_list_detail_download_story(workbench_client):
    client, _app = workbench_client
    raw = image_bytes()
    second = image_bytes("JPEG", color="orange")
    data = screenshot_archive(
        [{"path": "./assets/overview.png", "alt": "概览"}, {"path": "assets/second.jpg"}],
        {"package/assets/overview.png": raw, "package/assets/second.jpg": second},
    )
    uploaded = client.post(ROOT + "/admin/workbenches/imports", files={"file": ("fixture.tgz", data)}).json()["data"]
    assert uploaded["status"] == "completed"
    row = client.get(ROOT + "/workbenches").json()["data"]["data"][0]
    detail = client.get(ROOT + "/workbenches/" + row["id"]).json()["data"]
    assert row["screenshots"] == detail["screenshots"]
    assert row["cover"] == detail["cover"] == row["screenshots"][0]
    assert len(row["screenshots"]) == 2
    for image, expected in zip(row["screenshots"], [raw, second], strict=True):
        assert set(image) == {"id", "url", "sha256", "media_type", "width", "height", "bytes", "alt"}
        assert len(image["id"]) == 64
        response = client.get(image["url"])
        assert response.content == expected
        assert response.headers["content-type"] == image["media_type"]
        assert response.headers["etag"] == '"' + image["sha256"] + '"'
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get(detail["current_version"]["artifact_url"]).content == data
    invalid = client.get(row["cover"]["url"].rsplit("/", 1)[0] + "/" + "0" * 64)
    assert invalid.json()["status_code"] == 26207


def test_no_image_and_old_manifest_compatibility(service):
    task = service.import_bundle(2, 20, archive("1.0.0"))
    row = service.list(2)["data"][0]
    assert row["screenshots"] == [] and row["cover"] is None
    # Model a persisted entry imported by the previous backend, before this key existed.
    from bisheng.dsh_market.domain.models import MarketWorkbenchVersion

    with service.repository.sessions() as db:
        version = db.get(MarketWorkbenchVersion, task["version_id"])
        version.manifest = {key: value for key, value in version.manifest.items() if key != "screenshots"}
        db.add(version)
        db.commit()
    assert service.list(2)["data"][0]["screenshots"] == []
    assert service.detail(2, row["id"])["cover"] is None
    with pytest.raises(LookupError):
        service.screenshot(2, row["id"], task["version_id"], "0" * 64)


def test_invalid_api_declaration_returns_structured_error(workbench_client):
    client, _app = workbench_client
    data = screenshot_archive([{"path": "../bad.png"}])
    for path in ("/admin/workbenches/imports", "/admin/workbenches/imports/preview"):
        result = client.post(ROOT + path, files={"file": ("invalid.tgz", data)}).json()
        assert result["status_code"] == 26205
        assert result["data"]["rule"] == "WB-12"
        assert result["data"]["code"] == "WORKBENCH_SCREENSHOT_PATH"
        assert result["data"]["field"] == "dsh.workbench.screenshots[0].path"
    assert client.get(ROOT + "/workbenches").json()["data"]["total"] == 0


@pytest.mark.parametrize("alt", ["\ud800", "\udfff"])
def test_unpaired_surrogate_alt_rejected_without_changing_existing_entry(workbench_client, alt):
    client, _app = workbench_client
    imports = ROOT + "/admin/workbenches/imports"
    original = screenshot_archive()
    assert client.post(imports, files={"file": ("valid.tgz", original)}).json()["data"]["status"] == "completed"
    before = client.get(ROOT + "/workbenches").json()["data"]
    data = screenshot_archive([{"path": "assets/overview.png", "alt": alt}])
    for path in (imports, imports + "/preview"):
        result = client.post(path, files={"file": ("invalid.tgz", data)}).json()
        assert result["status_code"] == 26205
        assert result["data"]["rule"] == "WB-12"
        assert result["data"]["code"] == "WORKBENCH_SCREENSHOT_DECLARATION"
        assert result["data"]["field"] == "dsh.workbench.screenshots[0].alt"
    assert client.get(ROOT + "/workbenches").json()["data"] == before
    assert client.get(before["data"][0]["cover"]["url"]).content == image_bytes()


def test_tenant_account_and_unauthenticated_picture_access(workbench_client):
    client, app = workbench_client
    client.post(ROOT + "/admin/workbenches/imports", files={"file": ("fixture.tgz", screenshot_archive())})
    row = client.get(ROOT + "/workbenches").json()["data"]["data"][0]
    url = row["cover"]["url"]
    for actor in (MarketActor(2, 21), MarketActor(2, 22, desktop=True)):
        app.dependency_overrides[market_actor] = lambda actor=actor: actor
        assert client.get(url).status_code == 200  # Normal accounts may read tenant distribution settings.
        assert client.get(url).headers["content-type"] == "image/png"
    for actor in (MarketActor(3, 30), MarketActor(3, 31, global_super=True), MarketActor(3, 32, desktop=True)):
        app.dependency_overrides[market_actor] = lambda actor=actor: actor
        assert client.get(url).json()["status_code"] == 26207
        assert client.get(ROOT + "/workbenches").json()["data"]["total"] == 0
    del app.dependency_overrides[market_actor]
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_overwrite_upgrade_and_delete_invalidate_old_picture_urls(workbench_client):
    client, _app = workbench_client
    imports = ROOT + "/admin/workbenches/imports"
    first = screenshot_archive()
    client.post(imports, files={"file": ("first.tgz", first)})
    row = client.get(ROOT + "/workbenches").json()["data"]["data"][0]
    old_url = row["cover"]["url"]
    # Same image bytes but a changed artifact must change imageId, even for the same versionId.
    replacement = screenshot_archive(extra={"package/client.js": b"replacement code is never executed"})
    client.post(imports, files={"file": ("second.tgz", replacement)})
    second = client.get(ROOT + "/workbenches/" + row["id"]).json()["data"]
    assert second["current_version"]["id"] == row["current_version"]["id"]
    assert second["cover"]["sha256"] == row["cover"]["sha256"]
    assert second["cover"]["id"] != row["cover"]["id"]
    assert client.get(old_url).json()["status_code"] == 26207
    assert client.get(second["cover"]["url"]).status_code == 200
    client.post(imports, files={"file": ("upgrade.tgz", screenshot_archive(version="1.1.0"))})
    current = client.get(ROOT + "/workbenches/" + row["id"]).json()["data"]
    assert client.get(second["cover"]["url"]).json()["status_code"] == 26207
    assert client.get(second["current_version"]["artifact_url"]).json()["status_code"] == 26207
    client.delete(ROOT + "/admin/workbenches/" + row["id"], params={"revision": current["revision"]})
    assert client.get(current["cover"]["url"]).json()["status_code"] == 26207


@pytest.mark.parametrize("mutation", ["overwrite", "upgrade", "delete"])
def test_screenshot_rejects_concurrent_storage_changes(service, monkeypatch, mutation):
    service.import_bundle(2, 20, screenshot_archive())
    row = service.list(2)["data"][0]
    original_get = service.storage.get

    def mutate(tenant, digest):
        data = original_get(tenant, digest)
        if mutation == "delete":
            service.delete(2, 20, row["id"], row["revision"])
        else:
            service.import_bundle(
                2,
                20,
                screenshot_archive(
                    version="1.1.0" if mutation == "upgrade" else "1.0.0", extra={"package/client.js": b"changed"}
                ),
            )
        return data

    monkeypatch.setattr(service.storage, "get", mutate)
    with pytest.raises(WorkbenchArtifactError, match="changed"):
        service.screenshot(2, row["id"], row["current_version"]["id"], row["cover"]["id"])


def test_version_change_during_image_decode_is_rejected(service, monkeypatch):
    import bisheng.dsh_market.domain.workbench_service as module

    service.import_bundle(2, 20, screenshot_archive())
    row = service.list(2)["data"][0]
    read_image = module.read_workbench_screenshot

    def delete_after_decode(data, metadata):
        raw = read_image(data, metadata)
        service.delete(2, 20, row["id"], row["revision"])
        return raw

    monkeypatch.setattr(module, "read_workbench_screenshot", delete_after_decode)
    with pytest.raises(WorkbenchArtifactError, match="changed"):
        service.screenshot(2, row["id"], row["current_version"]["id"], row["cover"]["id"])


@pytest.mark.parametrize("field", ["sha256", "width"])
def test_persisted_image_binding_and_metadata_are_rechecked(service, field):
    from bisheng.dsh_market.domain.models import MarketWorkbenchVersion

    task = service.import_bundle(2, 20, screenshot_archive())
    row = service.list(2)["data"][0]
    with service.repository.sessions() as db:
        version = db.get(MarketWorkbenchVersion, task["version_id"])
        manifest = json.loads(json.dumps(version.manifest))
        manifest["screenshots"][0][field] = "0" * 64 if field == "sha256" else 999
        version.manifest = manifest
        db.add(version)
        db.commit()
    with pytest.raises(WorkbenchArtifactError):
        service.screenshot(2, row["id"], task["version_id"], row["cover"]["id"])


def test_eight_declared_images_allowed_and_links_rejected():
    raw = image_bytes()
    paths = [f"assets/{index}.png" for index in range(8)]
    data = screenshot_archive([{"path": path} for path in paths], {"package/" + path: raw for path in paths})
    assert len(validate_workbench_bundle(data)["screenshots"]) == 8
    output = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(screenshot_archive()), mode="r:gz") as original:
        with tarfile.open(fileobj=output, mode="w:gz") as target:
            for item in original:
                if item.name == "package/assets/overview.png":
                    item.type, item.size, item.linkname = tarfile.SYMTYPE, 0, "/tmp/secret.png"
                    target.addfile(item)
                else:
                    target.addfile(item, original.extractfile(item))
    with pytest.raises(WorkbenchBundleError, match="Only regular files"):
        validate_workbench_bundle(output.getvalue())


async def test_picture_route_preserves_verified_desktop_session_and_tenant(market_app, service):
    from bisheng.dsh_market.api.endpoints import router
    from bisheng.dsh_market.infrastructure import get_workbench_service
    from test.dsh.test_access import token

    app, sessions = market_app
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_workbench_service] = lambda: service
    service.import_bundle(2, 20, screenshot_archive())
    row = service.list(2)["data"][0]
    url = row["cover"]["url"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        response = await client.get(
            url,
            headers={
                "Authorization": "Bearer " + token(tenant_id="2"),
                "Cookie": "access_token_cookie=stale-browser-cookie",
                "x-dsh-market-tenant": "3",
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        sessions.active = False
        assert (await client.get(url, headers={"Authorization": "Bearer " + token(tenant_id="2")})).status_code == 401
        sessions.active = True
        assert (await client.get(url, headers={"Authorization": "Bearer " + token(tenant_id="3")})).json()[
            "status_code"
        ] == 26207


def test_picture_route_desktop_ownership_is_exact():
    from bisheng.utils.http_middleware import owns_dsh_credential

    url = ROOT + "/workbenches/" + "a" * 32 + "/versions/" + "b" * 32 + "/screenshots/" + "c" * 64
    assert owns_dsh_credential("GET", url)
    for method, path in [
        ("POST", url),
        ("DELETE", url),
        ("GET", url + "/extra"),
        ("GET", url[:-1]),
        ("GET", url.replace("/screenshots/", "/files/")),
    ]:
        assert not owns_dsh_credential(method, path)


@pytest.mark.parametrize("phase", ["fetch", "decode"])
@pytest.mark.parametrize("mutation", ["overwrite", "delete"])
def test_screenshot_rejects_restored_snapshot(workbench_client, service, monkeypatch, phase, mutation):
    import bisheng.dsh_market.domain.workbench_service as module

    client, _app = workbench_client
    original = screenshot_archive()
    service.import_bundle(2, 20, original)
    row = service.list(2)["data"][0]

    def restore():
        if mutation == "delete":
            service.delete(2, 20, row["id"], row["revision"])
        else:
            service.import_bundle(2, 20, screenshot_archive(extra={"package/client.js": b"replacement"}))
        service.import_bundle(2, 20, original)
        restored = service.list(2)["data"][0]
        assert restored["current_version"]["id"] == row["current_version"]["id"]
        assert restored["cover"]["id"] == row["cover"]["id"]
        assert restored["revision"] > row["revision"]

    if phase == "fetch":
        get = service.storage.get

        def fetch(tenant, digest):
            data = get(tenant, digest)
            restore()
            return data

        monkeypatch.setattr(service.storage, "get", fetch)
    else:
        decode = module.read_workbench_screenshot

        def read(data, metadata):
            raw = decode(data, metadata)
            restore()
            return raw

        monkeypatch.setattr(module, "read_workbench_screenshot", read)
    assert client.get(row["cover"]["url"]).json()["status_code"] == 26208


@pytest.mark.parametrize(
    "corruption",
    ["manifest", "screenshots", "entry", "id", "path", "sha256", "media_type", "width", "height", "bytes", "alt"],
)
def test_corrupt_persisted_screenshot_metadata_is_artifact_error(workbench_client, service, corruption):
    from bisheng.dsh_market.domain.models import MarketWorkbenchVersion

    client, _app = workbench_client
    task = service.import_bundle(2, 20, screenshot_archive())
    row = service.list(2)["data"][0]
    with service.repository.sessions() as db:
        version = db.get(MarketWorkbenchVersion, task["version_id"])
        manifest = json.loads(json.dumps(version.manifest))
        if corruption == "manifest":
            manifest = []
        elif corruption == "screenshots":
            manifest["screenshots"] = None
        elif corruption == "entry":
            manifest["screenshots"] = [None]
        else:
            del manifest["screenshots"][0][corruption]
        version.manifest = manifest
        db.add(version)
        db.commit()
    assert client.get(row["cover"]["url"]).json()["status_code"] == 26208


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "0" * 64),
        ("id", "invalid"),
        ("path", "assets/other.png"),
        ("path", "../bad.png"),
        ("sha256", "f" * 64),
        ("sha256", "not-a-hash"),
        ("media_type", "image/jpeg"),
        ("width", 8193),
        ("height", True),
        ("bytes", 5 * 1024 * 1024 + 1),
        ("alt", "bad\ntext"),
    ],
)
def test_invalid_persisted_screenshot_values_fail_all_routes(workbench_client, service, field, value):
    from bisheng.dsh_market.domain.models import MarketWorkbenchVersion

    client, _app = workbench_client
    task = service.import_bundle(2, 20, screenshot_archive())
    row = service.list(2)["data"][0]
    with service.repository.sessions() as db:
        version = db.get(MarketWorkbenchVersion, task["version_id"])
        manifest = json.loads(json.dumps(version.manifest))
        manifest["screenshots"][0][field] = value
        version.manifest = manifest
        db.add(version)
        db.commit()
    for url in (row["cover"]["url"], ROOT + "/workbenches", ROOT + "/workbenches/" + row["id"]):
        assert client.get(url).json()["status_code"] == 26208


def test_duplicate_persisted_screenshot_ids_fail_all_routes(workbench_client, service):
    from bisheng.dsh_market.domain.models import MarketWorkbenchVersion

    client, _app = workbench_client
    task = service.import_bundle(2, 20, screenshot_archive())
    row = service.list(2)["data"][0]
    with service.repository.sessions() as db:
        version = db.get(MarketWorkbenchVersion, task["version_id"])
        manifest = json.loads(json.dumps(version.manifest))
        manifest["screenshots"].append(dict(manifest["screenshots"][0]))
        version.manifest = manifest
        db.add(version)
        db.commit()
    for url in (row["cover"]["url"], ROOT + "/workbenches", ROOT + "/workbenches/" + row["id"]):
        assert client.get(url).json()["status_code"] == 26208


def test_screenshot_and_config_root_roundtrip(workbench_client):
    client, _app = workbench_client
    patch = workbench_fixtures.PATCH + "      config:\n        root: !!js dshHomePath('mind-workbench')\n"
    data = screenshot_archive(extra={"package/cordis.patch.yml": patch.encode()})
    result = client.post(ROOT + "/admin/workbenches/imports", files={"file": ("bundle.tgz", data)}).json()
    assert result["data"]["status"] == "completed"
    row = client.get(ROOT + "/workbenches").json()["data"]["data"][0]
    detail = client.get(ROOT + "/workbenches/" + row["id"]).json()["data"]
    assert client.get(detail["cover"]["url"]).content == image_bytes()
    assert client.get(detail["current_version"]["artifact_url"]).content == data


def test_tampered_artifact_is_not_served_as_picture(service):
    task = service.import_bundle(2, 20, screenshot_archive())
    row = service.list(2)["data"][0]
    service.storage.objects[2, task["digest"]] = b"corrupted archive"
    with pytest.raises(WorkbenchArtifactError, match="digest mismatch"):
        service.screenshot(2, row["id"], row["current_version"]["id"], row["cover"]["id"])
