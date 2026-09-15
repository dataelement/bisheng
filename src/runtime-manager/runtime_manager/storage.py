"""Per-app attachment storage handle (AC-45, design D10 — T084 / T085).

An application gets **one** storage space and never sees how it is made:
bucket, key prefix, endpoint and credentials all stay on this side. What the
app receives is a handle — an HTTP base URL and a bearer token, both injected
as ``BISHENG_APP_STORAGE_*`` at deploy time — and four operations on it:
upload, download, list, delete (plus metadata). F057's SDK ``storage`` module
is the consumer; the same names are what F053's ``bisheng dev`` injects locally
(as a directory handle there), so application code is identical in both.

Three properties are load bearing and each is pinned by ``tests/test_storage.py``:

* **Every key is forced under ``apps/{app_id}/attachments/``.** The scoping is
  done here, not by the caller: a key that tries to escape it (``..``, an
  absolute path, another app's ``apps/…`` prefix) is *rejected*, never
  silently rewritten into place. A rewrite would make "it worked" and "it
  landed somewhere else" indistinguishable to the app.
* **The bucket is ``bisheng-apps``, never the platform's ``bisheng``** (design
  pit 20). The public bucket is not anonymous-readable as a whole, but the
  platform's nginx forwards *any* key under ``/bisheng/`` to MinIO, so the
  bucket policy becomes the only wall. The attachment bucket has no nginx
  location and this module never writes a bucket policy — a fresh bucket is
  private by default and stays that way.
* **Not counted against the tenant storage quota, by construction.** This
  process holds no platform client (D3 / §4.3): there is no quota call to make
  and no ``tenant_id`` to make it with. The guarantee is the absence of a
  dependency, which is why it is asserted as such.

The single-file cap is a deployment setting (``RTM_STORAGE_MAX_FILE_MB``), and
an oversized upload is answered with an error *before* anything is written —
never a truncated object (F057 AC-22).

The MinIO SDK is imported inside :class:`MinioObjectStore` only, mirroring
``docker_backend``: the unit suite runs on ``tests/fakes.py::FakeObjectStore``
and needs neither the package nor a server.
"""

from __future__ import annotations

import logging
import posixpath
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from runtime_manager.config import Config, get_config
from runtime_manager.errors import NotFoundError, RuntimeManagerError

logger = logging.getLogger(__name__)

#: The platform's public bucket. Named here only so a test can assert we are
#: not it (pit 20).
PUBLIC_PLATFORM_BUCKET = "bisheng"

#: Namespace every app's objects live under. Keys handed in by an app are
#: *relative to* the app's own prefix and may never start with this segment —
#: that is the cross-app rejection.
APPS_NAMESPACE = "apps/"

#: S3's own limit; MinIO enforces it too, we just say it first.
MAX_KEY_BYTES = 1024

#: Injected environment names (the handle). Kept as constants so lifecycle,
#: the API and the backend-side contract (``app_runtime/domain/constants.py``)
#: spell them identically.
ENV_STORAGE_ENDPOINT = "BISHENG_APP_STORAGE_ENDPOINT"
ENV_STORAGE_TOKEN = "BISHENG_APP_STORAGE_TOKEN"
ENV_STORAGE_MAX_FILE_MB = "BISHENG_APP_STORAGE_MAX_FILE_MB"
STORAGE_ENV_NAMES: tuple[str, ...] = (ENV_STORAGE_ENDPOINT, ENV_STORAGE_TOKEN, ENV_STORAGE_MAX_FILE_MB)

DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 1000
DEFAULT_CONTENT_TYPE = "application/octet-stream"


# ---------------------------------------------------------------------------
# errors — same envelope as the rest of the manager (errors.py)
# ---------------------------------------------------------------------------


class StorageUnavailableError(RuntimeManagerError):
    """MinIO not configured or not reachable. Backend maps it like any 503."""

    code = "storage_unavailable"
    status = 503


class InvalidObjectKeyError(RuntimeManagerError):
    """The key would leave the app's space, or is not a key at all."""

    code = "invalid_object_key"
    status = 400


class PayloadTooLargeError(RuntimeManagerError):
    """Single-file cap exceeded (AC-45). Nothing was written."""

    code = "payload_too_large"
    status = 413


# ---------------------------------------------------------------------------
# object store protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObjectMeta:
    """What the app is allowed to know about one attachment.

    ``key`` here is always the *store* key (with the app prefix); the API strips
    the prefix before answering so the app only ever sees its own paths.
    """

    key: str
    size: int
    content_type: str = DEFAULT_CONTENT_TYPE
    etag: str = ""
    last_modified: str = ""


@runtime_checkable
class ObjectStore(Protocol):
    """The handful of S3 verbs this module needs. Keep it minimal."""

    def bucket_exists(self, bucket: str) -> bool: ...

    def make_bucket(self, bucket: str) -> None: ...

    def put_object(self, bucket: str, key: str, data: bytes, content_type: str) -> ObjectMeta: ...

    def stat_object(self, bucket: str, key: str) -> ObjectMeta | None: ...

    def get_object(self, bucket: str, key: str) -> tuple[ObjectMeta, Iterator[bytes]]: ...

    def list_objects(self, bucket: str, prefix: str, start_after: str, limit: int) -> list[ObjectMeta]: ...

    def remove_object(self, bucket: str, key: str) -> None: ...


class MinioObjectStore:
    """MinIO-backed :class:`ObjectStore`. The SDK is imported lazily, on first use."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client: Any | None = None

    def _minio(self):
        if self._client is None:
            try:
                from minio import Minio
            except ImportError as exc:  # pragma: no cover - packaging error, not a code path
                raise StorageUnavailableError(f"the minio package is not installed: {exc}")
            self._client = Minio(
                self._config.minio_endpoint,
                access_key=self._config.minio_access_key,
                secret_key=self._config.minio_secret_key,
                secure=self._config.minio_secure,
            )
        return self._client

    @staticmethod
    def _meta(key: str, stat: Any) -> ObjectMeta:
        last_modified = getattr(stat, "last_modified", None)
        return ObjectMeta(
            key=key,
            size=int(getattr(stat, "size", 0) or 0),
            content_type=getattr(stat, "content_type", None) or DEFAULT_CONTENT_TYPE,
            etag=getattr(stat, "etag", "") or "",
            last_modified=last_modified.isoformat() if last_modified else "",
        )

    def bucket_exists(self, bucket: str) -> bool:
        return bool(self._minio().bucket_exists(bucket))

    def make_bucket(self, bucket: str) -> None:
        # No policy call follows, on purpose: the bucket must stay private.
        self._minio().make_bucket(bucket)

    def put_object(self, bucket: str, key: str, data: bytes, content_type: str) -> ObjectMeta:
        import io

        result = self._minio().put_object(bucket, key, io.BytesIO(data), length=len(data), content_type=content_type)
        return ObjectMeta(key=key, size=len(data), content_type=content_type, etag=getattr(result, "etag", "") or "")

    def stat_object(self, bucket: str, key: str) -> ObjectMeta | None:
        from minio.error import S3Error

        try:
            return self._meta(key, self._minio().stat_object(bucket, key))
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                return None
            raise

    def get_object(self, bucket: str, key: str) -> tuple[ObjectMeta, Iterator[bytes]]:
        # Existence was already settled by the service's ``stat`` (one 404 path
        # for every store); this only streams.
        stat = self._minio().stat_object(bucket, key)
        meta = self._meta(key, stat)
        response = self._minio().get_object(bucket, key)

        def _chunks() -> Iterator[bytes]:
            try:
                yield from response.stream(64 * 1024)
            finally:
                response.close()
                response.release_conn()

        return meta, _chunks()

    def list_objects(self, bucket: str, prefix: str, start_after: str, limit: int) -> list[ObjectMeta]:
        out: list[ObjectMeta] = []
        for item in self._minio().list_objects(bucket, prefix=prefix, recursive=True, start_after=start_after or None):
            if getattr(item, "is_dir", False):
                continue
            out.append(self._meta(item.object_name, item))
            if len(out) >= limit:
                break
        return out

    def remove_object(self, bucket: str, key: str) -> None:
        self._minio().remove_object(bucket, key)


_store: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    """The process-wide store, created from config on first use.

    Raises :class:`StorageUnavailableError` when MinIO is not configured — the
    handle is still injected into apps (the env contract is unconditional), the
    calls just have nowhere to go, and the pre-flight names the missing vars.
    """
    global _store
    if _store is None:
        config = get_config()
        if not config.storage_configured:
            raise StorageUnavailableError(
                "attachment storage is not configured: set RTM_MINIO_ENDPOINT / "
                "RTM_MINIO_ACCESS_KEY / RTM_MINIO_SECRET_KEY on the runtime-manager"
            )
        _store = MinioObjectStore(config)
    return _store


def set_object_store(store: ObjectStore | None) -> None:
    """Injection seam used by tests and by the composition root."""
    global _store
    _store = store


# ---------------------------------------------------------------------------
# key scoping
# ---------------------------------------------------------------------------


def attachment_prefix(app_id: str) -> str:
    """``apps/{app_id}/attachments/`` — the only prefix an app can touch."""
    if not app_id or "/" in app_id or app_id in {".", ".."}:
        raise InvalidObjectKeyError(f"invalid app id {app_id!r}")
    return f"{APPS_NAMESPACE}{app_id}/attachments/"


def _reject(key: str, why: str) -> InvalidObjectKeyError:
    return InvalidObjectKeyError(f"object key {key!r} is not allowed: {why}", key=key)


def validate_key(key: str) -> str:
    """Return ``key`` unchanged if it is a well-formed *relative* attachment path.

    Rejects rather than normalises: ``a/../b`` is refused even though it would
    normalise to ``b``, because an app that wrote ``a/../b`` almost certainly
    meant to escape and the honest answer is "no", not "here is ``b``".
    """
    if not isinstance(key, str) or not key:
        raise _reject(key, "empty")
    if len(key.encode("utf-8")) > MAX_KEY_BYTES:
        raise _reject(key[:64] + "…", f"longer than {MAX_KEY_BYTES} bytes")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in key):
        raise _reject(key, "control characters")
    if "\\" in key:
        raise _reject(key, "backslashes")
    if key.startswith("/"):
        raise _reject(key, "absolute path")
    if key.endswith("/"):
        raise _reject(key, "trailing slash")
    segments = key.split("/")
    if any(seg in {"", ".", ".."} for seg in segments):
        raise _reject(key, "empty, '.' or '..' path segment")
    if posixpath.normpath(key) != key:
        raise _reject(key, "not in normal form")
    if key.startswith(APPS_NAMESPACE):
        # ``apps/other-app/attachments/x`` is the cross-app shape. It would
        # nest harmlessly under our own prefix, but accepting it teaches the
        # app that the namespace is addressable — it is not.
        raise _reject(key, f"'{APPS_NAMESPACE}' is a reserved namespace")
    return key


def validate_prefix(prefix: str) -> str:
    """List filter: empty, or a key optionally ending in ``/``."""
    if prefix in ("", None):
        return ""
    if prefix.startswith(APPS_NAMESPACE):
        raise _reject(prefix, f"'{APPS_NAMESPACE}' is a reserved namespace")
    if prefix.endswith("/"):
        validate_key(prefix[:-1])
        return prefix
    validate_key(prefix)
    return prefix


def scoped_key(app_id: str, key: str) -> str:
    """The store key for an app-relative key, after validation."""
    return attachment_prefix(app_id) + validate_key(key)


def unscoped_key(app_id: str, store_key: str) -> str:
    prefix = attachment_prefix(app_id)
    if not store_key.startswith(prefix):
        # Cannot happen when the store honours ``prefix`` — and if it ever
        # does, leaking another app's key is the worst possible outcome.
        raise NotFoundError("object is outside this application's storage")
    return store_key[len(prefix) :]


# ---------------------------------------------------------------------------
# the handle, manager side
# ---------------------------------------------------------------------------


def mint_storage_token() -> str:
    """Per-app bearer token; 256 bits, URL-safe, never logged (readonly redacts it)."""
    return secrets.token_urlsafe(32)


def storage_endpoint_for(config: Config, app_id: str) -> str:
    """``BISHENG_APP_STORAGE_ENDPOINT`` value for one app."""
    return f"{config.app_facing_base}/v1/apps/{app_id}/storage"


def storage_env(config: Config, *, app_id: str, token: str) -> dict[str, str]:
    """The three injected variables (contract §5). Names are the contract."""
    return {
        ENV_STORAGE_ENDPOINT: storage_endpoint_for(config, app_id),
        ENV_STORAGE_TOKEN: token,
        ENV_STORAGE_MAX_FILE_MB: str(config.storage_max_file_mb),
    }


class AppStorageService:
    """Four operations, all scoped to one app's prefix, all on the private bucket."""

    def __init__(self, config: Config, store: ObjectStore | None = None) -> None:
        self._config = config
        self._store_override = store
        self._bucket_ready = False

    @property
    def bucket(self) -> str:
        return self._config.storage_bucket

    def _store(self) -> ObjectStore:
        return self._store_override if self._store_override is not None else get_object_store()

    def _ensure_bucket(self, store: ObjectStore) -> None:
        if self._bucket_ready:
            return
        if self.bucket == PUBLIC_PLATFORM_BUCKET:
            # Refuse to operate at all rather than put attachments where nginx
            # can serve them (pit 20). A config typo must not become a leak.
            raise StorageUnavailableError(
                f"RTM_STORAGE_BUCKET must not be the platform's public bucket {PUBLIC_PLATFORM_BUCKET!r}"
            )
        try:
            if not store.bucket_exists(self.bucket):
                store.make_bucket(self.bucket)
        except RuntimeManagerError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"attachment storage is not reachable: {exc}")
        self._bucket_ready = True

    def _ready(self) -> ObjectStore:
        store = self._store()
        self._ensure_bucket(store)
        return store

    # -- operations --------------------------------------------------------
    def upload(self, app_id: str, key: str, data: bytes, content_type: str | None = None) -> ObjectMeta:
        """Write one object. Over the cap → 413 before a single byte is stored."""
        store_key = scoped_key(app_id, key)
        self.check_size(len(data))
        store = self._ready()
        try:
            meta = store.put_object(self.bucket, store_key, data, content_type or DEFAULT_CONTENT_TYPE)
        except RuntimeManagerError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"attachment upload failed: {exc}")
        return self._public(app_id, meta)

    def check_size(self, size: int) -> None:
        cap = self._config.storage_max_file_bytes
        if size > cap:
            raise PayloadTooLargeError(
                f"file is {size} bytes; the single-file limit is {self._config.storage_max_file_mb} MB",
                max_file_mb=self._config.storage_max_file_mb,
            )

    def stat(self, app_id: str, key: str) -> ObjectMeta:
        store_key = scoped_key(app_id, key)
        store = self._ready()
        try:
            meta = store.stat_object(self.bucket, store_key)
        except RuntimeManagerError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"attachment metadata read failed: {exc}")
        if meta is None:
            raise NotFoundError(f"attachment {key!r} does not exist", key=key)
        return self._public(app_id, meta)

    def download(self, app_id: str, key: str) -> tuple[ObjectMeta, Iterator[bytes]]:
        """Stream one object; a missing one is a 404 from ``stat`` before any transfer starts."""
        self.stat(app_id, key)
        store_key = scoped_key(app_id, key)
        store = self._ready()
        try:
            meta, chunks = store.get_object(self.bucket, store_key)
        except RuntimeManagerError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"attachment download failed: {exc}")
        return self._public(app_id, meta), chunks

    def list(
        self, app_id: str, prefix: str = "", cursor: str | None = None, limit: int = DEFAULT_LIST_LIMIT
    ) -> dict[str, Any]:
        """Paginated listing under the app prefix; ``next_cursor`` is a key to resume after."""
        base = attachment_prefix(app_id)
        store_prefix = base + validate_prefix(prefix)
        start_after = base + validate_key(cursor) if cursor else ""
        limit = max(1, min(int(limit), MAX_LIST_LIMIT))
        store = self._ready()
        try:
            rows = store.list_objects(self.bucket, store_prefix, start_after, limit + 1)
        except RuntimeManagerError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"attachment listing failed: {exc}")
        # Defensive filter: the store honours ``prefix``, but a listing that
        # returned someone else's key must never reach the app.
        rows = [r for r in rows if r.key.startswith(base)]
        page = rows[:limit]
        objects = [self._public(app_id, r) for r in page]
        next_cursor = objects[-1].key if len(rows) > limit and objects else None
        return {"objects": objects, "next_cursor": next_cursor}

    def delete(self, app_id: str, key: str) -> None:
        """Remove one object; a missing one is a 404, not a silent success (F057 AC-25)."""
        self.stat(app_id, key)
        store = self._ready()
        try:
            store.remove_object(self.bucket, scoped_key(app_id, key))
        except RuntimeManagerError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"attachment delete failed: {exc}")

    def purge_app(self, app_id: str) -> int:
        """Delete everything under the app's prefix (AC-43 explicit delete). Returns the count."""
        base = attachment_prefix(app_id)
        store = self._ready()
        removed = 0
        start_after = ""
        while True:
            rows = store.list_objects(self.bucket, base, start_after, MAX_LIST_LIMIT)
            rows = [r for r in rows if r.key.startswith(base)]
            if not rows:
                return removed
            for row in rows:
                store.remove_object(self.bucket, row.key)
                removed += 1
            start_after = rows[-1].key

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _public(app_id: str, meta: ObjectMeta) -> ObjectMeta:
        return ObjectMeta(
            key=unscoped_key(app_id, meta.key),
            size=meta.size,
            content_type=meta.content_type,
            etag=meta.etag,
            last_modified=meta.last_modified,
        )


def storage_preflight(config: Config) -> dict[str, Any]:
    """``runtime/status`` pre-flight row for the attachment handle.

    Two ways this is misconfigured and neither shows up anywhere else: MinIO
    not set (every SDK storage call 503s), and — systemd shape — the manager
    listening on loopback, which no app container can dial. The second one
    is the reachability gap of the handle: the injected endpoint is derived
    from ``RTM_HOST`` unless ``RTM_APP_FACING_BASE_URL`` says otherwise.
    """
    name = "attachment_storage"
    if not config.storage_configured:
        return {
            "name": name,
            "ok": False,
            "detail": (
                "not configured — set RTM_MINIO_ENDPOINT / RTM_MINIO_ACCESS_KEY / "
                "RTM_MINIO_SECRET_KEY; hosted apps' storage calls answer 503 until then"
            ),
        }
    if config.storage_bucket == PUBLIC_PLATFORM_BUCKET:
        return {
            "name": name,
            "ok": False,
            "detail": f"RTM_STORAGE_BUCKET={PUBLIC_PLATFORM_BUCKET} is the platform's public bucket — use bisheng-apps",
        }
    base = config.app_facing_base
    if not config.app_facing_base_url and config.host in {"127.0.0.1", "localhost", "::1"}:
        return {
            "name": name,
            "ok": False,
            "detail": (
                f"apps would be told to reach this process at {base}, which is loopback and unreachable "
                "from the application network — set RTM_APP_FACING_BASE_URL (and RTM_HOST) to the "
                f"{config.network} bridge gateway address, e.g. http://172.18.0.1:{config.port}"
            ),
        }
    return {
        "name": name,
        "ok": True,
        "detail": f"bucket {config.storage_bucket} on {config.minio_endpoint}; apps dial {base}",
    }
