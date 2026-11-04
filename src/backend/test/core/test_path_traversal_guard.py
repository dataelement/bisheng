"""Issue #1994: a file name is data, not a path.

Upload headers, MinIO keys and stored file entries all reach code that joins
them onto a directory. `../../x` and `/etc/x` both walk out of a plain join, so
the write has to be pinned to the directory rather than trusted to the callers
that build the name.
"""

import tempfile
from pathlib import Path

import pytest

from bisheng.core.cache.utils import resolve_inside, save_download_file

TRAVERSALS = [
    "../../../tmp/pwned.php",
    "/tmp/pwned.php",
    "a/../../../tmp/pwned.php",
]

# Payloads that defeat a normalizer elsewhere but are ordinary names to POSIX:
# `....` is just a directory, and a backslash is a filename character. They must
# stay inside rather than be rejected -- over-refusing breaks real uploads.
NOT_TRAVERSAL_ON_POSIX = [
    "....//....//tmp/pwned.php",
    "..\\..\\..\\tmp\\pwned.php",
]


@pytest.fixture
def root(tmp_path) -> Path:
    (tmp_path / "keep").mkdir()
    return tmp_path


def test_a_plain_name_lands_in_the_directory(root):
    assert resolve_inside(root, "report.docx") == (root / "report.docx").resolve()


def test_a_folder_upload_sub_path_is_still_allowed(root):
    """Linsight rebuilds the uploaded directory tree, so separators are legitimate."""
    assert resolve_inside(root, "年报/2024/Q1.md") == (root / "年报/2024/Q1.md").resolve()


def test_several_parts_join_like_os_path_join(root):
    assert resolve_inside(root, "uploads", "x.xlsx") == (root / "uploads" / "x.xlsx").resolve()


@pytest.mark.parametrize("name", TRAVERSALS)
def test_anything_leaving_the_directory_is_refused(root, name):
    with pytest.raises(ValueError):
        resolve_inside(root, name)


def test_a_name_that_only_looks_like_traversal_is_kept(root):
    """`..stuff` is a perfectly ordinary file name."""
    assert resolve_inside(root, "..hidden.md") == (root / "..hidden.md").resolve()


@pytest.mark.parametrize("name", TRAVERSALS + NOT_TRAVERSAL_ON_POSIX)
def test_an_uploaded_file_cannot_be_written_outside_the_cache(monkeypatch, name):
    """The name arrives from the upload's multipart header, unfiltered."""
    cache = tempfile.mkdtemp(prefix="bisheng_cache_")
    monkeypatch.setattr("bisheng.core.cache.utils.CACHE_DIR", cache)

    stored = Path(save_download_file(b"payload", "bisheng", name))

    assert stored.resolve().is_relative_to(Path(cache).resolve())
    # Separators collapse into the single stored segment rather than failing the
    # write, which is what the bare hash prefix used to do.
    assert stored.parent.resolve() == (Path(cache) / "bisheng").resolve()
    assert stored.read_bytes() == b"payload"


def test_an_ordinary_upload_keeps_its_name(monkeypatch):
    cache = tempfile.mkdtemp(prefix="bisheng_cache_")
    monkeypatch.setattr("bisheng.core.cache.utils.CACHE_DIR", cache)

    stored = Path(save_download_file(b"payload", "bisheng", "委托书.pdf"))

    assert stored.name.endswith("_委托书.pdf")


@pytest.mark.parametrize("name", NOT_TRAVERSAL_ON_POSIX)
def test_a_name_the_filesystem_does_not_read_as_traversal_is_allowed(root, name):
    assert resolve_inside(root, name).is_relative_to(root.resolve())
