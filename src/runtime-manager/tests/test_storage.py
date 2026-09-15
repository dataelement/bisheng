"""Attachment storage handle — the four operations and their cage (AC-45, T084a).

The assertions are against the *store calls*, not the store contents: the
guarantee under test is "which bucket, which key did we ask for", because that
is the layer this process owns. Whether MinIO honours a key is MinIO's business;
whether we ever send it a key outside ``apps/{app_id}/attachments/`` is ours.

Two of these are absence tests and rot silently if nobody re-reads them:

* the bucket is ``bisheng-apps`` and **no bucket policy is ever written** —
  design pit 20: the public ``bisheng`` bucket sits behind an nginx location
  that forwards any key to MinIO, so "private" there is one policy edit away
  from "public";
* there is **no tenant-quota accounting** — this process has no platform
  client, so the guarantee is a missing dependency, not a flag.
"""

from __future__ import annotations

import inspect

import pytest

from runtime_manager.desired_state import get_store
from runtime_manager.errors import NotFoundError
from runtime_manager.storage import (
    APPS_NAMESPACE,
    PUBLIC_PLATFORM_BUCKET,
    STORAGE_ENV_NAMES,
    AppStorageService,
    InvalidObjectKeyError,
    PayloadTooLargeError,
    StorageUnavailableError,
    attachment_prefix,
    storage_preflight,
    validate_key,
)
from tests.fakes import FakeHostProbe

APP = "app-1"
OTHER = "app-2"
BUCKET = "bisheng-apps"


def _service(config, store) -> AppStorageService:
    return AppStorageService(config, store=store)


def _deploy(config, fake_docker, app_id: str = APP, slug: str = "sales-report"):
    """One running instance so the bearer path has a record to check against."""
    from runtime_manager.admission import AdmissionService
    from runtime_manager.api.schemas import DeployRequest, TierIn
    from runtime_manager.lifecycle import LifecycleService

    class _Ready:
        def wait_ready(self, container, port, health_path, timeout=None):
            class _Outcome:
                ready = True
                reason = ""

            return _Outcome()

    service = LifecycleService(
        config,
        docker=fake_docker,
        admission=AdmissionService(config, host_probe=FakeHostProbe()),
        prober=_Ready(),
    )
    service.deploy(
        DeployRequest(
            app_id=app_id,
            slug=slug,
            version_id="ver-0123456789abcdef",
            version_no=1,
            image_ref="bisheng-app/x:1",
            tier=TierIn(cpu=0.5, mem=512),
            port=8080,
            env={},
            platform_api_base="https://bisheng.example.com/api",
        )
    )
    return get_store(config).get(app_id).env["BISHENG_APP_STORAGE_TOKEN"]


# ---------------------------------------------------------------------------
# service — scoping
# ---------------------------------------------------------------------------


def test_four_operations_scoped_to_app_prefix(rtm_config, fake_object_store):
    """AC-45 — put / get / stat / delete / list all address ``apps/{app_id}/attachments/``."""
    svc = _service(rtm_config, fake_object_store)
    prefix = attachment_prefix(APP)
    assert prefix == f"{APPS_NAMESPACE}{APP}/attachments/"

    meta = svc.upload(APP, "reports/q3.pdf", b"%PDF", "application/pdf")
    assert meta.key == "reports/q3.pdf"  # the app never sees the prefix
    assert fake_object_store.calls_of("put_object")[0]["key"] == prefix + "reports/q3.pdf"

    stat = svc.stat(APP, "reports/q3.pdf")
    assert stat.size == 4 and stat.content_type == "application/pdf"
    assert fake_object_store.calls_of("stat_object")[0]["key"] == prefix + "reports/q3.pdf"

    got, chunks = svc.download(APP, "reports/q3.pdf")
    assert b"".join(chunks) == b"%PDF"
    assert got.key == "reports/q3.pdf"
    assert fake_object_store.calls_of("get_object")[0]["key"] == prefix + "reports/q3.pdf"

    page = svc.list(APP)
    assert [o.key for o in page["objects"]] == ["reports/q3.pdf"]
    assert fake_object_store.calls_of("list_objects")[0]["prefix"] == prefix

    svc.delete(APP, "reports/q3.pdf")
    assert fake_object_store.calls_of("remove_object")[0]["key"] == prefix + "reports/q3.pdf"
    assert fake_object_store.keys(BUCKET) == []

    # Every single key that reached the store carried the app prefix.
    for _name, kwargs in fake_object_store.calls:
        if "key" in kwargs:
            assert kwargs["key"].startswith(prefix)


def test_list_never_shows_another_apps_objects(rtm_config, fake_object_store):
    svc = _service(rtm_config, fake_object_store)
    svc.upload(APP, "mine.txt", b"a")
    svc.upload(OTHER, "theirs.txt", b"b")

    assert [o.key for o in svc.list(APP)["objects"]] == ["mine.txt"]
    assert [o.key for o in svc.list(OTHER)["objects"]] == ["theirs.txt"]
    with pytest.raises(NotFoundError):
        svc.stat(APP, "theirs.txt")


def test_list_is_paginated_with_a_stable_cursor(rtm_config, fake_object_store):
    svc = _service(rtm_config, fake_object_store)
    for i in range(5):
        svc.upload(APP, f"f{i}.txt", b"x")

    first = svc.list(APP, limit=2)
    assert [o.key for o in first["objects"]] == ["f0.txt", "f1.txt"]
    assert first["next_cursor"] == "f1.txt"
    second = svc.list(APP, cursor=first["next_cursor"], limit=2)
    assert [o.key for o in second["objects"]] == ["f2.txt", "f3.txt"]
    last = svc.list(APP, cursor=second["next_cursor"], limit=2)
    assert [o.key for o in last["objects"]] == ["f4.txt"]
    assert last["next_cursor"] is None
    # Prefix filter stays inside the app.
    assert svc.list(APP, prefix="f4")["objects"][0].key == "f4.txt"


@pytest.mark.parametrize(
    "key",
    [
        "../app-2/attachments/x.txt",
        "reports/../../app-2/attachments/x.txt",
        "apps/app-2/attachments/x.txt",  # another app's full prefix
        "apps/app-1/attachments/x.txt",  # even our own — the namespace is not addressable
        "/etc/passwd",
        "a//b.txt",
        "./a.txt",
        "a/./b.txt",
        "dir/",
        "",
        "a\\b.txt",
        "a\x00b",
        "x" * 1025,
    ],
)
def test_cross_app_key_rejected(rtm_config, fake_object_store, key):
    """AC-45 — an escaping key is refused, never silently rewritten into place."""
    svc = _service(rtm_config, fake_object_store)
    for op in (
        lambda: svc.upload(APP, key, b"x"),
        lambda: svc.download(APP, key),
        lambda: svc.stat(APP, key),
        lambda: svc.delete(APP, key),
    ):
        with pytest.raises(InvalidObjectKeyError) as excinfo:
            op()
        assert excinfo.value.status_code == 400
        assert excinfo.value.detail["code"] == "invalid_object_key"
    # Nothing reached the store: rejection happens before any I/O.
    assert not fake_object_store.calls_of("put_object")
    assert not fake_object_store.calls_of("remove_object")


def test_cursor_and_prefix_are_validated_like_keys(rtm_config, fake_object_store):
    svc = _service(rtm_config, fake_object_store)
    with pytest.raises(InvalidObjectKeyError):
        svc.list(APP, cursor="../app-2/attachments/x")
    with pytest.raises(InvalidObjectKeyError):
        svc.list(APP, prefix="../")
    with pytest.raises(InvalidObjectKeyError):
        svc.list(APP, prefix="apps/")


def test_well_formed_keys_pass_unchanged():
    for key in ("a.txt", "reports/2026/q3.pdf", "中文 名字.docx", "a-b_c.d"):
        assert validate_key(key) == key


def test_key_length_cap_counts_the_app_prefix(rtm_config, fake_object_store):
    """S3's 1024 bytes apply to the *scoped* key: a 400 here, not a 503 after the round trip."""
    svc = _service(rtm_config, fake_object_store)
    room = 1024 - len(attachment_prefix(APP).encode())
    svc.upload(APP, "x" * room, b"a")  # exactly fits with the prefix
    with pytest.raises(InvalidObjectKeyError):
        svc.upload(APP, "x" * (room + 1), b"a")  # fits alone, not once scoped
    assert len(fake_object_store.calls_of("put_object")) == 1


# ---------------------------------------------------------------------------
# service — cap, bucket, quota
# ---------------------------------------------------------------------------


def test_single_file_size_limit_enforced(rtm_config, fake_object_store):
    """AC-45 — over the cap is an error before any byte is written, never a truncated object."""
    config = rtm_config.with_overrides(storage_max_file_mb=1)
    svc = _service(config, fake_object_store)

    svc.upload(APP, "ok.bin", b"x" * (1024 * 1024))  # exactly the cap is fine
    with pytest.raises(PayloadTooLargeError) as excinfo:
        svc.upload(APP, "big.bin", b"x" * (1024 * 1024 + 1))

    assert excinfo.value.status_code == 413
    assert excinfo.value.detail["code"] == "payload_too_large"
    assert excinfo.value.detail["max_file_mb"] == 1
    assert fake_object_store.keys(BUCKET) == [attachment_prefix(APP) + "ok.bin"]


def test_bucket_is_bisheng_apps_not_public_bucket(rtm_config, fake_object_store):
    """Pit 20 — separate private bucket, created on demand, **no policy ever written**."""
    assert rtm_config.storage_bucket == BUCKET
    assert BUCKET != PUBLIC_PLATFORM_BUCKET
    svc = _service(rtm_config, fake_object_store)

    svc.upload(APP, "a.txt", b"a")

    assert fake_object_store.calls_of("make_bucket") == [{"bucket": BUCKET}]
    assert {kw["bucket"] for _n, kw in fake_object_store.calls} == {BUCKET}
    assert fake_object_store.calls_of("set_bucket_policy") == []
    assert fake_object_store.policies == {}
    # A second call does not re-check the bucket — nor does a second service
    # instance: the router builds one per request, the round trip is per process.
    svc.upload(APP, "b.txt", b"b")
    _service(rtm_config, fake_object_store).upload(APP, "c.txt", b"c")
    assert len(fake_object_store.calls_of("bucket_exists")) == 1
    assert fake_object_store.calls_of("make_bucket") == [{"bucket": BUCKET}]


def test_public_bucket_is_refused_outright(rtm_config, fake_object_store):
    """A config typo pointing at ``bisheng`` must fail closed, not leak."""
    public = rtm_config.with_overrides(storage_bucket=PUBLIC_PLATFORM_BUCKET)
    svc = _service(public, fake_object_store)
    with pytest.raises(StorageUnavailableError):
        svc.upload(APP, "a.txt", b"a")
    assert fake_object_store.calls == []
    # …and the pre-flight names it before any app tries.
    check = storage_preflight(
        public.with_overrides(minio_endpoint="minio:9000", minio_access_key="k", minio_secret_key="s")
    )
    assert check["ok"] is False and PUBLIC_PLATFORM_BUCKET in check["detail"]


def test_not_counted_into_tenant_storage_quota(rtm_config, fake_object_store):
    """AC-45 — no quota call exists to make: no tenant input, no platform client."""
    import runtime_manager.storage as storage_module

    svc = _service(rtm_config, fake_object_store)
    for op in (svc.upload, svc.download, svc.stat, svc.list, svc.delete):
        params = inspect.signature(op).parameters
        assert "tenant_id" not in params and "quota" not in params
    # No platform client of any kind: nothing to call a quota on. The only
    # first-party imports are config / errors — the process stays platform-blind (D3).
    source = inspect.getsource(storage_module)
    assert "httpx" not in source
    first_party = {line.split()[1] for line in source.splitlines() if line.startswith("from runtime_manager.")}
    assert first_party == {"runtime_manager.config", "runtime_manager.errors"}
    svc.upload(APP, "a.txt", b"a" * 1000)
    assert {name for name, _ in fake_object_store.calls} <= {"bucket_exists", "make_bucket", "put_object"}


def test_unconfigured_store_answers_503_not_500(rtm_config):
    """No MinIO → a distinguishable error (F057 AC-25), and the pre-flight names the fix."""
    from runtime_manager.storage import set_object_store

    set_object_store(None)
    assert rtm_config.storage_configured is False
    with pytest.raises(StorageUnavailableError) as excinfo:
        AppStorageService(rtm_config).upload(APP, "a.txt", b"a")
    assert excinfo.value.status_code == 503
    assert "RTM_MINIO_ENDPOINT" in excinfo.value.detail["message"]

    check = storage_preflight(rtm_config)
    assert check["name"] == "attachment_storage" and check["ok"] is False
    assert "RTM_MINIO_ENDPOINT" in check["detail"]


def test_store_outage_is_503(rtm_config, fake_object_store):
    fake_object_store.reachable = False
    with pytest.raises(StorageUnavailableError):
        _service(rtm_config, fake_object_store).upload(APP, "a.txt", b"a")


def test_preflight_flags_a_loopback_endpoint(rtm_config):
    """systemd shape: 127.0.0.1 is unreachable from the bridge — say so before an app finds out."""
    configured = rtm_config.with_overrides(minio_endpoint="minio:9000", minio_access_key="k", minio_secret_key="s")
    loopback = storage_preflight(configured.with_overrides(host="127.0.0.1"))
    assert loopback["ok"] is False and "RTM_APP_FACING_BASE_URL" in loopback["detail"]

    explicit = storage_preflight(
        configured.with_overrides(host="127.0.0.1", app_facing_base_url="http://172.18.0.1:8091")
    )
    assert explicit["ok"] is True
    compose = storage_preflight(configured.with_overrides(host="0.0.0.0"))
    assert compose["ok"] is True


def test_missing_attachment_is_404_not_empty(rtm_config, fake_object_store):
    """F057 AC-25 — distinguishable errors, never an empty body pretending to be a file."""
    svc = _service(rtm_config, fake_object_store)
    for op in (
        lambda: svc.stat(APP, "nope.txt"),
        lambda: svc.download(APP, "nope.txt"),
        lambda: svc.delete(APP, "nope.txt"),
    ):
        with pytest.raises(NotFoundError):
            op()


# ---------------------------------------------------------------------------
# MinIO adapter — the SDK edge cases we translate (stubbed SDK, no server)
# ---------------------------------------------------------------------------


class _S3Error(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _StubResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.closed = False
        self.released = False

    def stream(self, size):
        yield self._data

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


class _StubMinio:
    """Just enough of ``minio.Minio`` to pin our translation of its answers."""

    def __init__(self) -> None:
        from types import SimpleNamespace

        self.ns = SimpleNamespace
        self.objects: dict[str, bytes] = {}
        self.policy_calls = 0

    def bucket_exists(self, bucket):
        return True

    def put_object(self, bucket, key, stream, length, content_type):
        self.objects[key] = stream.read()
        return self.ns(etag="e1")

    def stat_object(self, bucket, key):
        if key not in self.objects:
            raise _S3Error("NoSuchKey")
        return self.ns(size=len(self.objects[key]), content_type="text/plain", etag="e1", last_modified=None)

    def get_object(self, bucket, key):
        return _StubResponse(self.objects[key])

    def list_objects(self, bucket, prefix, recursive, start_after):
        yield self.ns(object_name=prefix, is_dir=True)  # the SDK's directory marker
        for key in sorted(self.objects):
            if key.startswith(prefix) and (not start_after or key > start_after):
                yield self.ns(
                    object_name=key,
                    is_dir=False,
                    size=len(self.objects[key]),
                    content_type=None,
                    etag="e1",
                    last_modified=None,
                )

    def remove_object(self, bucket, key):
        self.objects.pop(key, None)

    def set_bucket_policy(self, *a, **kw):
        self.policy_calls += 1


def test_minio_adapter_translates_sdk_answers(rtm_config, monkeypatch):
    """``NoSuchKey`` → ``None``; directory markers skipped; response released after streaming."""
    from runtime_manager.storage import MinioObjectStore

    stub = _StubMinio()
    monkeypatch.setattr(MinioObjectStore, "_minio", lambda self: stub)
    # ``from minio.error import S3Error`` inside the adapter resolves to our stub.
    import sys
    import types

    error_module = types.ModuleType("minio.error")
    error_module.S3Error = _S3Error
    monkeypatch.setitem(sys.modules, "minio", types.ModuleType("minio"))
    monkeypatch.setitem(sys.modules, "minio.error", error_module)

    adapter = MinioObjectStore(rtm_config)
    assert adapter.stat_object(BUCKET, "apps/app-1/attachments/nope") is None
    put = adapter.put_object(BUCKET, "apps/app-1/attachments/a.txt", b"hi", "text/plain")
    assert put.size == 2 and put.etag == "e1"
    assert adapter.stat_object(BUCKET, "apps/app-1/attachments/a.txt").content_type == "text/plain"

    meta, chunks = adapter.get_object(BUCKET, "apps/app-1/attachments/a.txt")
    assert b"".join(chunks) == b"hi" and meta.size == 2

    listed = adapter.list_objects(BUCKET, "apps/app-1/attachments/", "", 10)
    assert [o.key for o in listed] == ["apps/app-1/attachments/a.txt"]
    assert listed[0].content_type == "application/octet-stream"  # SDK ``None`` normalised
    adapter.remove_object(BUCKET, "apps/app-1/attachments/a.txt")
    assert adapter.stat_object(BUCKET, "apps/app-1/attachments/a.txt") is None
    assert stub.policy_calls == 0


# ---------------------------------------------------------------------------
# env injection (T085)
# ---------------------------------------------------------------------------


def test_storage_env_names_are_the_contract():
    assert STORAGE_ENV_NAMES == (
        "BISHENG_APP_STORAGE_ENDPOINT",
        "BISHENG_APP_STORAGE_TOKEN",
        "BISHENG_APP_STORAGE_MAX_FILE_MB",
    )


def test_destroy_with_purge_removes_attachments(rtm_config, fake_docker, fake_object_store, monkeypatch):
    """AC-43 — the owner's explicit delete takes the attachment space with it; plain destroy does not."""
    from runtime_manager.lifecycle import LifecycleService

    _deploy(rtm_config, fake_docker)
    svc = _service(rtm_config, fake_object_store)
    svc.upload(APP, "keep-until-purge.txt", b"x")
    svc.upload(OTHER, "untouched.txt", b"y")

    LifecycleService(rtm_config, docker=fake_docker).destroy(APP, purge_volume=False)
    assert attachment_prefix(APP) + "keep-until-purge.txt" in fake_object_store.keys(BUCKET)

    LifecycleService(rtm_config, docker=fake_docker).destroy(APP, purge_volume=True)
    assert fake_object_store.keys(BUCKET) == [attachment_prefix(OTHER) + "untouched.txt"]


def test_destroy_purge_survives_a_store_outage(rtm_config, fake_docker, fake_object_store):
    """The delete already happened; a store that is down must not un-happen it."""
    from runtime_manager.lifecycle import LifecycleService

    _deploy(rtm_config, fake_docker)
    fake_object_store.reachable = False
    assert LifecycleService(rtm_config, docker=fake_docker).destroy(APP, purge_volume=True) == {}
    assert get_store(rtm_config).get(APP) is None
