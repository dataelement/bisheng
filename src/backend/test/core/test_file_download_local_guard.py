"""F072: ``file_download`` / ``async_file_download`` accept bare local paths only
inside the process's own download directories.

``POST /finetune/job/file/preset`` handed the user-supplied ``files`` string
straight to ``async_file_download``; "the file exists" was the only check, so
``/etc/passwd`` was uploaded to MinIO and served back.
"""

import pytest

from bisheng.core.cache import utils


@pytest.fixture
def roots(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setattr(utils, "_LOCAL_FILE_ROOTS", (allowed,))
    return allowed, other


def test_file_inside_allowed_root_is_returned(roots):
    allowed, _ = roots
    f = allowed / "abc_report.pdf"
    f.write_bytes(b"x")
    path, name = utils.file_download(str(f))
    assert path == str(f)
    assert name == "report.pdf"


async def test_async_file_inside_allowed_root_is_returned(roots):
    allowed, _ = roots
    f = allowed / "abc_report.pdf"
    f.write_bytes(b"x")
    path, name = await utils.async_file_download(str(f))
    assert path == str(f)
    assert name == "report.pdf"


def test_existing_file_outside_roots_is_rejected(roots):
    _, other = roots
    f = other / "passwd"
    f.write_bytes(b"root:x:0:0")
    with pytest.raises(ValueError):
        utils.file_download(str(f))


async def test_async_existing_file_outside_roots_is_rejected(roots):
    _, other = roots
    f = other / "passwd"
    f.write_bytes(b"root:x:0:0")
    with pytest.raises(ValueError):
        await utils.async_file_download(str(f))


def test_traversal_from_allowed_root_is_rejected(roots):
    allowed, other = roots
    f = other / "passwd"
    f.write_bytes(b"root:x:0:0")
    with pytest.raises(ValueError):
        utils.file_download(str(allowed / ".." / "other" / "passwd"))


def test_symlink_inside_root_pointing_outside_is_rejected(roots):
    allowed, other = roots
    target = other / "passwd"
    target.write_bytes(b"root:x:0:0")
    link = allowed / "link"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        utils.file_download(str(link))


def test_query_string_is_stripped_before_the_check(roots):
    _, other = roots
    f = other / "passwd"
    f.write_bytes(b"root:x:0:0")
    with pytest.raises(ValueError):
        utils.file_download(f"{f}?X-Amz-Algorithm=AWS4")


def test_default_roots_cover_cache_and_tempdir():
    import tempfile
    from pathlib import Path

    resolved = {r.resolve() for r in utils._LOCAL_FILE_ROOTS}
    assert Path(utils.CACHE_DIR).resolve() in resolved
    assert Path(tempfile.gettempdir()).resolve() in resolved
