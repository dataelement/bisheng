"""T010 — package receipt: unpack safety, the three volume gates, snapshot layout (AC-02 / AC-43).

The six malicious entry kinds are the reason this file is long. The repository's
only prior unpack path (``linsight/.../skill_store.py`` ``_safe_rel_path``)
handles a **zip**, which can only carry absolute paths and ``..``. A tar can
also carry symlinks, hardlinks, device nodes and FIFOs — a symlink pointing at
``/etc/passwd`` turns the next write into a host escape, and a hardlink lets the
unpacked tree read any file the backend user can (design 坑 15). Copying the zip
guard verbatim would look complete and cover a third of the attack surface.

The volume gates are three, not one, because they fail for different reasons:
the upload gate sees compressed bytes, the unpacked gate catches a tar bomb that
sails through it, and the entry gate catches a million empty files that trip
neither.

Two assertions here are about *how* rather than *what*, and both are deliberate:
the upload must reach MinIO as a path (never ``await file.read()``, which puts a
50 MB package in the API worker's heap), and the private bucket must be created
by this service rather than by ``_init_bucket_conf`` — that function also
attaches an anonymous read policy, and nginx proxies the public bucket's keys to
the internet (design K5 / 坑 13/14).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio

APP_ID = "app-f055-pkg"
VERSION_ID = "ver-f055-pkg"


@pytest.fixture(autouse=True)
def _reset_bucket_cache():
    """The "bucket already ensured" flag is process-level; tests must not inherit it."""
    from bisheng.app_publish.domain.services import package_service

    package_service.reset_bucket_cache()
    yield
    package_service.reset_bucket_cache()


def _extract(tar_path: Path, dest: Path):
    from bisheng.app_publish.domain.services.package_service import safe_extract

    return safe_extract(tar_path, dest)


# ---------------------------------------------------------------------------
# Unpack safety — six entry kinds, one code (16202)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "kwargs"),
    [
        ("absolute_path", {"absolute_path": True}),
        ("traversal", {"traversal": True}),
        ("symlink", {"symlink": True}),
        ("hardlink", {"hardlink": True}),
        ("device", {"device": True}),
        ("fifo", {"fifo": True}),
    ],
)
async def test_reject_illegal_entry_kinds(tmp_path, tarball_factory, kind, kwargs):
    from bisheng.common.errcode.app_publish import AppPackageInvalidError

    package = tarball_factory(**kwargs)
    with pytest.raises(AppPackageInvalidError) as excinfo:
        _extract(package, tmp_path / "out")
    assert excinfo.value.code == 16202
    assert excinfo.value.kwargs["details"]["reason"] == kind, (
        f"the caller must be told which entry kind tripped, got {excinfo.value.kwargs['details']}"
    )
    # Nothing escaped: the destination holds no file outside itself.
    assert not (tmp_path / "escaped.txt").exists()
    assert not Path("/etc/cron.d/pwn").exists()


async def test_valid_package_extracts_completely(tmp_path, tarball_factory):
    """The guard must not be so eager that an ordinary package fails."""
    result = _extract(tarball_factory(), tmp_path / "out")
    names = {path.name for path in result.root.rglob("*") if path.is_file()}
    assert {"bisheng-app.yaml", "main.py", "requirements.txt"} <= names
    assert result.entries >= 3
    assert result.unpacked_bytes > 0


# ---------------------------------------------------------------------------
# The three volume gates (AC-02)
# ---------------------------------------------------------------------------


async def test_reject_over_max_package_mb_16201(tmp_path, tarball_factory, app_runtime_settings):
    """The upload gate reads deployment configuration, not a constant (F053 AC-32 depends on it)."""
    from bisheng.app_publish.domain.services.package_service import check_upload_size
    from bisheng.common.errcode.app_publish import AppPackageTooLargeError

    app_runtime_settings(max_package_mb=1)
    with pytest.raises(AppPackageTooLargeError) as excinfo:
        check_upload_size(2 * 1024 * 1024)
    assert excinfo.value.code == 16201
    assert excinfo.value.kwargs["details"]["gate"] == "package_mb"
    assert excinfo.value.kwargs["details"]["limit"] == 1

    check_upload_size(1024)  # under the ceiling: no exception


async def test_reject_over_max_unpacked_mb(tmp_path, tarball_factory, app_runtime_settings):
    """A tar bomb: 8 MB of zeros gzip to a few KB, so only the unpacked gate can see it."""
    from bisheng.common.errcode.app_publish import AppPackageTooLargeError

    app_runtime_settings(max_unpacked_mb=2, max_package_mb=50, max_package_entries=20000)
    package = tarball_factory(payload_mb=8)
    assert package.stat().st_size < 2 * 1024 * 1024, "the upload gate must not be what catches this"

    with pytest.raises(AppPackageTooLargeError) as excinfo:
        _extract(package, tmp_path / "out")
    assert excinfo.value.kwargs["details"]["gate"] == "unpacked_mb"


async def test_reject_over_max_package_entries(tmp_path, tarball_factory, app_runtime_settings):
    from bisheng.common.errcode.app_publish import AppPackageTooLargeError

    app_runtime_settings(max_package_entries=50, max_unpacked_mb=200)
    with pytest.raises(AppPackageTooLargeError) as excinfo:
        _extract(tarball_factory(entries=200), tmp_path / "out")
    assert excinfo.value.kwargs["details"]["gate"] == "entries"


async def test_missing_manifest_is_16203_not_a_package_error(tmp_path, tarball_factory):
    """"You forgot the manifest" is its own code — it is a fixable authoring mistake, not a broken package."""
    from bisheng.app_publish.domain.services.package_service import read_manifest_bytes
    from bisheng.common.errcode.app_publish import AppManifestMissingError

    result = _extract(tarball_factory(include_manifest=False), tmp_path / "out")
    with pytest.raises(AppManifestMissingError) as excinfo:
        read_manifest_bytes(result.root)
    assert excinfo.value.code == 16203


# ---------------------------------------------------------------------------
# Snapshot storage (AC-02 / AC-43)
# ---------------------------------------------------------------------------


async def test_snapshot_key_layout_matches_f054(tmp_path, tarball_factory, fake_minio):
    """``apps/{app_id}/versions/{version_id}/code.tar.gz`` — F054's layout, written once."""
    from bisheng.app_publish.domain.services.package_service import APPS_BUCKET, snapshot_key, store_package

    package = tarball_factory()
    key = await store_package(package, app_id=APP_ID, version_id=VERSION_ID)

    assert key == f"apps/{APP_ID}/versions/{VERSION_ID}/code.tar.gz" == snapshot_key(APP_ID, VERSION_ID)
    put = [call for call in fake_minio.calls if call[0] == "put_object"]
    assert put and put[0][1]["bucket_name"] == APPS_BUCKET, "code snapshots never land in the public bucket (K5)"


async def test_upload_never_read_into_memory(tmp_path, tarball_factory, fake_minio):
    """``put_object(file=Path(...))`` → ``fput_object``; ``await file.read()`` would heap a 50 MB package."""
    from bisheng.app_publish.domain.services.package_service import store_package

    await store_package(tarball_factory(), app_id=APP_ID, version_id=VERSION_ID)
    put = [call for call in fake_minio.calls if call[0] == "put_object"]
    assert put[0][1]["from_path"] is True


async def test_bucket_ensured_idempotently_on_first_use(tmp_path, tarball_factory, fake_minio):
    """The private bucket is this service's business — ``_init_bucket_conf`` stays untouched (坑 14)."""
    import inspect

    from bisheng.app_publish.domain.services.package_service import APPS_BUCKET, store_package
    from bisheng.core.storage.minio.minio_storage import MinioStorage

    await store_package(tarball_factory(), app_id=APP_ID, version_id="v1")
    await store_package(tarball_factory(), app_id=APP_ID, version_id="v2")

    assert fake_minio.created_buckets == [APPS_BUCKET], "ensure once per process, not once per upload"
    assert APPS_BUCKET not in inspect.getsource(MinioStorage._init_bucket_conf), (
        "the shared bucket initializer also attaches an anonymous read policy; the code bucket must stay out of it"
    )


async def test_snapshot_immutable_and_retrievable(tmp_path, tarball_factory, fake_minio):
    """AC-43: any version's snapshot comes back byte-for-byte, for review / preview / rollback."""
    from bisheng.app_publish.domain.services.package_service import fetch_package, store_package

    package = tarball_factory()
    original = package.read_bytes()
    key = await store_package(package, app_id=APP_ID, version_id=VERSION_ID)

    assert await fetch_package(key) == original
    # A second publish of the same app writes a different key rather than overwriting.
    other = await store_package(tarball_factory(extra_files={"extra.py": "x = 1\n"}), app_id=APP_ID, version_id="v2")
    assert other != key
    assert await fetch_package(key) == original


async def test_orphan_cleanup_on_next_deploy_same_app(publish_db, tmp_path, tarball_factory, fake_minio, app_factory, deployment_factory):
    """Failed attempts keep their snapshot 7 days for debugging, then the next deploy of that app sweeps it (D2).

    Driven from ``app_deployment`` rather than by listing the bucket: every key
    the pipeline ever wrote is recorded on a row that is never deleted, so the
    table *is* the index — and a sweep that only deletes keys it can account for
    can never take out a snapshot some other feature put there.
    """
    from sqlalchemy import update

    from bisheng.app_publish.domain.models.app_deployment import STATUS_FAILED, AppDeployment
    from bisheng.app_publish.domain.services.package_service import cleanup_orphans, store_package

    app_row, live_version = await app_factory()

    stale_key = await store_package(tarball_factory(), app_id=app_row.id, version_id="stale-version")
    fresh_key = await store_package(tarball_factory(), app_id=app_row.id, version_id="fresh-version")
    kept_key = await store_package(tarball_factory(), app_id=app_row.id, version_id=live_version.id)

    stale = await deployment_factory(app_id=app_row.id, status=STATUS_FAILED, version_id="stale-version", code_object_key=stale_key)
    await deployment_factory(app_id=app_row.id, status=STATUS_FAILED, version_id="fresh-version", code_object_key=fresh_key)
    await deployment_factory(app_id=app_row.id, status=STATUS_FAILED, version_id=live_version.id, code_object_key=kept_key)

    async with publish_db() as session:
        await session.exec(
            update(AppDeployment)
            .where(AppDeployment.id == stale.id)
            .values(create_time=datetime.now() - timedelta(days=30))
        )
        await session.commit()

    removed = await cleanup_orphans(app_row.id)

    assert removed == [stale_key]
    assert await fetch_or_none(fresh_key) is not None, "a recent failure keeps its snapshot for debugging"
    assert await fetch_or_none(kept_key) is not None, "a snapshot a version row points at is never an orphan"
    assert await fetch_or_none(stale_key) is None


async def fetch_or_none(key: str):
    from bisheng.app_publish.domain.services.package_service import fetch_package

    return await fetch_package(key)
