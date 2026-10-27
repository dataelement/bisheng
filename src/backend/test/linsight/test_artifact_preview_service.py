"""F111: task-mode pptx preview service.

Covers AC-22 (cached preview reused), AC-23 (failure → 11025, nothing cached, retry
on next open), AC-24 (download-equivalent access + file ownership), AC-25 (both
share shapes), AC-27 (single flight) and AC-28 (the download endpoint keeps its
behaviour after the shared access check is extracted). MinIO, Redis and
LibreOffice are faked; CI needs none of them.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import fitz
import pytest

from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.linsight import LinsightArtifactPreviewError
from bisheng.linsight.domain.services import artifact_preview_service as svc_mod
from bisheng.linsight.domain.services.artifact_preview_service import LinsightArtifactPreviewService

SVID = "ver-1"
OWNER = 7
FILE_KEY = f"linsight/final_result/{SVID}/abc123.pptx"
PREVIEW_KEY = f"linsight/preview/{SVID}/abc123.pdf"


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeMinio:
    bucket = "bisheng"

    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.puts = []
        self.gets = []

    async def object_exists(self, bucket_name=None, object_name=None):
        return object_name in self.objects

    async def get_object(self, bucket_name=None, object_name=None):
        self.gets.append(object_name)
        return self.objects.get(object_name)

    async def put_object(self, *, bucket_name=None, object_name, file, content_type="application/octet-stream"):
        self.puts.append(object_name)
        self.objects[object_name] = file

    async def get_share_link(self, object_name, bucket=None, clear_host=True, expire_days=7):
        return f"/bisheng/{object_name}?sig=1"


class FakeRedisConn:
    def __init__(self, held=False):
        self.keys = {"held"} if held else set()
        self.set_calls = []

    async def set(self, key, value, nx=False, ex=None):
        self.set_calls.append((key, nx, ex))
        if nx and key in self.keys:
            return None
        self.keys.add(key)
        return True


class FakeRedis:
    def __init__(self, held=False):
        self.async_connection = FakeRedisConn()
        if held:
            self.async_connection.keys.add(f"linsight:pptx_preview:{SVID}:abc123")
        self.deleted = []

    async def acluster_nodes(self, key):
        return None

    async def adelete(self, key):
        self.deleted.append(key)
        self.async_connection.keys.discard(key)


def _version(user_id=OWNER, session_id="sess-1"):
    return SimpleNamespace(id=SVID, user_id=user_id, session_id=session_id)


def _user(user_id=OWNER, admin=False):
    return SimpleNamespace(user_id=user_id, is_admin=lambda: admin)


def _pdf_bytes(pages=2) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture()
def env(monkeypatch):
    state = SimpleNamespace(
        minio=FakeMinio({FILE_KEY: b"PK-fake-pptx"}),
        redis=FakeRedis(),
        converted=[],
        convert_result="ok",
        pages=2,
        version=_version(),
    )

    async def fake_minio():
        return state.minio

    async def fake_redis():
        return state.redis

    async def fake_get_by_id(svid):
        return state.version if svid == SVID else None

    def fake_convert(input_path, output_dir=None, timeout=180):
        state.converted.append((os.path.basename(input_path), timeout))
        if state.convert_result is None:
            return None
        os.makedirs(output_dir, exist_ok=True)
        out = os.path.join(output_dir, os.path.splitext(os.path.basename(input_path))[0] + ".pdf")
        with open(out, "wb") as fh:
            fh.write(_pdf_bytes(state.pages) if state.pages else b"%PDF-1.4\n%%EOF\n")
        return out

    monkeypatch.setattr(svc_mod, "get_minio_storage", fake_minio)
    monkeypatch.setattr(svc_mod, "get_redis_client", fake_redis)
    monkeypatch.setattr(svc_mod.LinsightSessionVersionDao, "get_by_id", staticmethod(fake_get_by_id))
    monkeypatch.setattr(svc_mod, "convert_ppt_to_pdf", fake_convert)
    return state


# --------------------------------------------------------------------------- #
# access (AC-24 / AC-25 / AC-28)
# --------------------------------------------------------------------------- #
async def test_owner_and_admin_may_access(env):
    assert (await LinsightArtifactPreviewService.load_accessible_version(SVID, _user(), None)).id == SVID
    assert (await LinsightArtifactPreviewService.load_accessible_version(SVID, _user(99, admin=True), None)).id == SVID


async def test_both_share_shapes_grant_access(env):
    by_session = SimpleNamespace(resource_id="sess-1", meta_data=None)
    by_version = SimpleNamespace(resource_id="other", meta_data={"versionId": SVID})
    for link in (by_session, by_version):
        version = await LinsightArtifactPreviewService.load_accessible_version(SVID, _user(99), link)
        assert version.id == SVID


async def test_stranger_is_rejected(env):
    with pytest.raises(UnAuthorizedError):
        await LinsightArtifactPreviewService.load_accessible_version(SVID, _user(99), None)
    wrong_link = SimpleNamespace(resource_id="other", meta_data={"versionId": "ver-2"})
    with pytest.raises(UnAuthorizedError):
        await LinsightArtifactPreviewService.load_accessible_version(SVID, _user(99), wrong_link)


async def test_missing_version_is_not_found(env):
    with pytest.raises(NotFoundError):
        await LinsightArtifactPreviewService.load_accessible_version("nope", _user(), None)


@pytest.mark.parametrize(
    "bad_key",
    [
        "linsight/final_result/ver-2/abc123.pptx",  # another version
        f"linsight/final_result/{SVID}/../ver-2/abc123.pptx",  # traversal
        f"linsight/final_result/{SVID}/abc123.docx",  # not a slide deck
        "knowledge/original/1.pptx",  # outside task results
    ],
)
async def test_foreign_or_odd_file_keys_are_rejected_without_converting(env, bad_key):
    with pytest.raises(UnAuthorizedError):
        await LinsightArtifactPreviewService.get_pptx_preview(env.version, bad_key)
    assert env.converted == [] and env.minio.puts == []


async def test_bucket_prefixed_key_is_accepted(env):
    result = await LinsightArtifactPreviewService.get_pptx_preview(env.version, f"/bisheng/{FILE_KEY}")
    assert result["status"] == "ready"


# --------------------------------------------------------------------------- #
# cache, single flight, failure (AC-22 / AC-23 / AC-27)
# --------------------------------------------------------------------------- #
async def test_first_open_converts_caches_and_releases_lock(env):
    result = await LinsightArtifactPreviewService.get_pptx_preview(env.version, FILE_KEY)
    assert result == {"status": "ready", "file_path": f"/bisheng/{PREVIEW_KEY}?sig=1"}
    assert env.minio.puts == [PREVIEW_KEY]
    assert env.converted and env.converted[0][1] == 120
    lock = f"linsight:pptx_preview:{SVID}:abc123"
    assert (lock, True, 180) in env.redis.async_connection.set_calls
    assert env.redis.deleted == [lock]


async def test_cached_preview_is_returned_without_converting(env):
    env.minio.objects[PREVIEW_KEY] = b"%PDF"
    result = await LinsightArtifactPreviewService.get_pptx_preview(env.version, FILE_KEY)
    assert result["status"] == "ready"
    assert env.converted == [] and env.minio.gets == []


async def test_lock_held_elsewhere_reports_converting(env):
    env.redis = FakeRedis(held=True)
    result = await LinsightArtifactPreviewService.get_pptx_preview(env.version, FILE_KEY)
    assert result == {"status": "converting"}
    assert env.converted == [] and env.redis.deleted == []


@pytest.mark.parametrize("mode", ["none", "zero_pages"])
async def test_failed_conversion_raises_11025_caches_nothing_and_retries(env, mode):
    if mode == "none":
        env.convert_result = None
    else:
        env.pages = 0
    with pytest.raises(LinsightArtifactPreviewError):
        await LinsightArtifactPreviewService.get_pptx_preview(env.version, FILE_KEY)
    assert env.minio.puts == []
    assert env.redis.deleted == [f"linsight:pptx_preview:{SVID}:abc123"], "lock released after failure"

    env.convert_result, env.pages = "ok", 2
    result = await LinsightArtifactPreviewService.get_pptx_preview(env.version, FILE_KEY)
    assert result["status"] == "ready" and len(env.converted) == 2


async def test_missing_source_object_is_a_preview_failure(env):
    env.minio.objects.pop(FILE_KEY)
    with pytest.raises(LinsightArtifactPreviewError):
        await LinsightArtifactPreviewService.get_pptx_preview(env.version, FILE_KEY)
    assert env.converted == []


# --------------------------------------------------------------------------- #
# the download endpoint after the refactor (AC-28)
# --------------------------------------------------------------------------- #
async def test_download_endpoint_still_signs_the_requested_key(env, monkeypatch):
    from bisheng.linsight.api.endpoints import linsight as endpoint

    monkeypatch.setattr(endpoint, "get_minio_storage", lambda: _awaitable(env.minio))
    resp = await endpoint.linsight_file_download(
        file_url=f"/bisheng/{FILE_KEY}", session_version_id=SVID, login_user=_user(), share_link=None
    )
    assert resp.data == {"file_path": f"/bisheng/{FILE_KEY}?sig=1"}
    with pytest.raises(UnAuthorizedError):
        await endpoint.linsight_file_download(
            file_url=FILE_KEY, session_version_id=SVID, login_user=_user(99), share_link=None
        )


async def _awaitable(value):
    return value
