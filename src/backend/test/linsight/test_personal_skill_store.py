"""Personal skill bundles use their own object prefix and fixed size caps."""

import io
import struct
import zipfile
from types import SimpleNamespace

import pytest

from bisheng.common.errcode.linsight import (
    SkillArchiveDamagedError,
    SkillArchiveEncryptedError,
    SkillBundleTooLargeError,
    SkillEmptyFileError,
    SkillEntryLimitError,
    SkillFileTooLargeError,
    SkillManifestMissingError,
    SkillManifestTooLargeError,
    SkillMultipleError,
    SkillPathEscapeError,
    SkillTypeMismatchError,
    SkillValidationError,
)
from bisheng.linsight.domain.services import skill_store
from bisheng.linsight.domain.services.skill_store import (
    PERSONAL_ENTRY_MAX_COUNT,
    PERSONAL_SKILL_MD_MAX_BYTES,
    PERSONAL_UNPACKED_MAX_BYTES,
    PERSONAL_UPLOAD_MAX_BYTES,
    SKILL_MD,
    SkillStore,
    accept_skill_upload,
)
from test.linsight.fixtures.fake_minio import FakeMinioStorage

MB = 1024 * 1024
USER = 11
OTHER = 22


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in entries.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _zip_declared_size(declared: int) -> bytes:
    """A tiny archive whose central directory claims ``declared`` unpacked bytes."""
    raw = bytearray(_zip_bytes({SKILL_MD: b"x"}))
    local = raw.find(b"PK\x03\x04")
    central = raw.rfind(b"PK\x01\x02")
    struct.pack_into("<I", raw, local + 22, declared)
    struct.pack_into("<I", raw, central + 24, declared)
    return bytes(raw)


def _encrypted_zip() -> bytes:
    """Set the encryption flag in the headers. zipfile will not write that bit itself."""
    raw = bytearray(_zip_bytes({SKILL_MD: b"secret"}))
    local = raw.find(b"PK\x03\x04")
    central = raw.rfind(b"PK\x01\x02")
    struct.pack_into("<H", raw, local + 6, struct.unpack_from("<H", raw, local + 6)[0] | 0x1)
    struct.pack_into("<H", raw, central + 8, struct.unpack_from("<H", raw, central + 8)[0] | 0x1)
    return bytes(raw)


def _conf(monkeypatch, upload_mb: int, unpacked_mb: int) -> None:
    async def _aget(self):
        return SimpleNamespace(skill_upload_max_size_mb=upload_mb, skill_unpacked_max_size_mb=unpacked_mb)

    monkeypatch.setattr(type(skill_store.bisheng_settings), "aget_linsight_conf", _aget)


def _code(exc: BaseException) -> int:
    return exc.code


@pytest.fixture
def store(tmp_path):
    return SkillStore(root=tmp_path, minio=FakeMinioStorage())


class TestPersonalSkillStore:
    def test_personal_key_and_delete_stay_in_that_users_prefix(self, store):
        files = {SKILL_MD: b"---\nname: pdf\ndescription: d\n---\n"}
        enterprise = store.write_bundle(1, "pdf", files)
        owned = store.write_bundle(1, "pdf", files, owner_user_id=USER)
        other = store.write_bundle(1, "pdf", {SKILL_MD: b"other"}, owner_user_id=OTHER)

        assert owned.object_key == f"linsight/personal-skills/1/{USER}/pdf/{owned.content_hash}.zip"
        assert enterprise.object_key.startswith("linsight/skills/1/pdf/")
        assert store.read_text(1, "pdf", owned.content_hash, owner_user_id=USER) == files[SKILL_MD].decode()

        assert store.delete(1, "pdf", owner_user_id=USER)
        assert not store.exists(1, "pdf", owned.content_hash, owner_user_id=USER)
        assert store.exists(1, "pdf", enterprise.content_hash)
        assert store.exists(1, "pdf", other.content_hash, owner_user_id=OTHER)
        assert store.minio.keys("linsight/skills/1/pdf/")
        assert store.minio.keys(f"linsight/personal-skills/1/{OTHER}/pdf/")
        assert store.minio.keys(f"linsight/personal-skills/1/{USER}/pdf/") == []

    async def test_personal_size_caps_are_fixed(self, store, monkeypatch):
        _conf(monkeypatch, 500, 800)
        assert PERSONAL_UPLOAD_MAX_BYTES == 52428800
        assert PERSONAL_UNPACKED_MAX_BYTES == 209715200

        with pytest.raises(SkillFileTooLargeError) as upload_error:
            await store.publish_upload(
                1,
                "pdf",
                "pdf.md",
                b"x" * (PERSONAL_UPLOAD_MAX_BYTES + 1),
                owner_user_id=USER,
                content_type="text/plain",
            )
        assert _code(upload_error.value) == 11052
        assert upload_error.value.kwargs["limit_mb"] == 50

        with pytest.raises(SkillBundleTooLargeError) as unpacked_error:
            await store.publish_upload(
                1,
                "pdf",
                "pdf.zip",
                _zip_declared_size(PERSONAL_UNPACKED_MAX_BYTES + 1),
                owner_user_id=USER,
                content_type="application/zip",
            )
        assert _code(unpacked_error.value) == 11059
        assert unpacked_error.value.kwargs["limit_mb"] == 200

        with pytest.raises(SkillManifestTooLargeError) as manifest_error:
            await store.publish_upload(
                1,
                "pdf",
                "pdf.md",
                b"a" * (PERSONAL_SKILL_MD_MAX_BYTES + 1),
                owner_user_id=USER,
                content_type="text/plain",
            )
        assert _code(manifest_error.value) == 11073
        assert manifest_error.value.kwargs["limit_mb"] == 1

        entries = {SKILL_MD: b"ok", **{f"f{i}.txt": b"a" for i in range(PERSONAL_ENTRY_MAX_COUNT)}}
        with pytest.raises(SkillEntryLimitError) as entry_error:
            await store.publish_upload(
                1, "pdf", "pdf.zip", _zip_bytes(entries), owner_user_id=USER, content_type="application/zip"
            )
        assert _code(entry_error.value) == 11074
        assert entry_error.value.kwargs["limit_count"] == 1000
        assert store.minio.put_calls == 0

    async def test_personal_caps_ignore_a_smaller_system_config(self, store, monkeypatch):
        _conf(monkeypatch, 1, 1)
        files = await accept_skill_upload("pdf.md", b"hello", owner_user_id=USER, content_type="text/plain")
        assert files[SKILL_MD] == b"hello"

    async def test_enterprise_path_uses_the_configured_cap(self, store, monkeypatch):
        _conf(monkeypatch, 3, 9)
        with pytest.raises(SkillFileTooLargeError) as upload_error:
            await store.publish_upload(
                1, "pdf", "pdf.md", b"x" * (3 * MB + 1), owner_user_id=0, content_type="text/plain"
            )
        assert upload_error.value.kwargs["limit_mb"] == 3

        with pytest.raises(SkillBundleTooLargeError) as unpacked_error:
            await store.publish_upload(
                1,
                "pdf",
                "pdf.zip",
                _zip_declared_size(9 * MB + 1),
                owner_user_id=0,
                content_type="application/zip",
            )
        assert unpacked_error.value.kwargs["limit_mb"] == 9
        assert store.minio.put_calls == 0

    async def test_rejected_archives_do_not_write(self, store):
        cases = [
            ("pdf.zip", _encrypted_zip(), "application/zip", SkillArchiveEncryptedError, 11063),
            ("pdf.zip", b"PK\x03\x04not-a-zip", "application/zip", SkillArchiveDamagedError, 11067),
            ("pdf.zip", _zip_bytes({"readme.md": b"no manifest"}), "application/zip", SkillManifestMissingError, 11068),
            (
                "pdf.zip",
                _zip_bytes({SKILL_MD: b"ok", "../evil.md": b"x"}),
                "application/zip",
                SkillPathEscapeError,
                11069,
            ),
            ("pdf.md", b"", "text/plain", SkillEmptyFileError, 11071),
            (
                "pdf.zip",
                _zip_bytes({"a/SKILL.md": b"a", "b/SKILL.md": b"b"}),
                "application/zip",
                SkillMultipleError,
                11072,
            ),
            ("notes.txt", b"hello", "text/plain", SkillValidationError, 11051),
        ]
        for filename, data, mime, error_type, code in cases:
            with pytest.raises(error_type) as caught:
                await store.publish_upload(1, "pdf", filename, data, owner_user_id=USER, content_type=mime)
            assert _code(caught.value) == code
        assert store.minio.put_calls == 0

    @pytest.mark.parametrize(
        ("filename", "data", "mime"),
        [
            ("pdf.md", b"PK\x03\x04rest", "text/plain"),
            ("pdf.md", b"hello", "application/zip"),
            ("pdf.zip", b"not-a-zip", "application/zip"),
            ("pdf.skill", b"not-a-zip", "application/octet-stream"),
            ("pdf.zip", _zip_bytes({SKILL_MD: b"ok"}), "text/plain"),
        ],
    )
    async def test_type_must_match_extension_and_bytes(self, store, filename, data, mime):
        with pytest.raises(SkillTypeMismatchError) as caught:
            await store.publish_upload(1, "pdf", filename, data, owner_user_id=USER, content_type=mime)
        assert _code(caught.value) == 11065
        assert store.minio.put_calls == 0

    async def test_allowed_mime_and_empty_mime_pass(self, store):
        payload = _zip_bytes({SKILL_MD: b"ok"})
        for filename, data, mime in (
            ("pdf.md", b"hello", "text/markdown"),
            ("pdf.md", b"hello", "text/x-markdown"),
            ("pdf.md", b"hello", "text/plain; charset=utf-8"),
            ("pdf.md", b"hello", None),
            ("pdf.zip", payload, "application/zip"),
            ("pdf.skill", payload, "application/x-zip-compressed"),
            ("pdf.zip", payload, ""),
        ):
            files = await accept_skill_upload(filename, data, owner_user_id=USER, content_type=mime)
            assert SKILL_MD in files
