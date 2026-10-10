"""F072: an uploaded HTML must not pull arbitrary server files into the knowledge base.

``HTML2MarkdownConverter`` resolves ``<img src>`` against the HTML's own
directory as a ``file://`` base, so ``file:///etc/passwd`` and a relative
``../../secret`` both used to be ``shutil.copy``'d into MinIO. Only files that
live under the source HTML's directory may be copied.
"""

import os
from pathlib import Path

import pytest

from bisheng.knowledge.rag.pipeline.loader.utils.md_from_html import HTML2MarkdownConverter

SIBLING_BYTES = b"\x89PNG sibling image"
SECRET_BYTES = b"root:x:0:0:root:/root:/bin/bash\n"


@pytest.fixture
def workspace(tmp_path_factory):
    html_dir = tmp_path_factory.mktemp("html")
    outside_dir = tmp_path_factory.mktemp("outside")
    (html_dir / "ok.png").write_bytes(SIBLING_BYTES)
    secret = outside_dir / "secret.txt"
    secret.write_bytes(SECRET_BYTES)
    return html_dir, secret


def _media_files(output_dir: Path) -> list[Path]:
    return [p for p in output_dir.rglob("media_*") if p.is_file()]


def _convert(html_dir: Path, body: str, tmp_path: Path) -> Path:
    html = html_dir / "doc.html"
    html.write_text(f"<html><body><h1>Normal</h1>{body}</body></html>", encoding="utf-8")
    out = tmp_path / "out"
    converter = HTML2MarkdownConverter(output_dir=str(out), media_download_timeout=1)
    md_path = converter.convert(str(html), output_filename_stem="doc")
    assert md_path and Path(md_path).exists()
    return out


def test_absolute_file_uri_outside_html_dir_is_not_copied(workspace, tmp_path):
    html_dir, secret = workspace
    out = _convert(html_dir, f'<img src="{secret.as_uri()}">', tmp_path)
    assert _media_files(out) == []


def test_relative_traversal_outside_html_dir_is_not_copied(workspace, tmp_path):
    html_dir, secret = workspace
    rel = os.path.relpath(secret, html_dir)
    assert rel.startswith("..")
    out = _convert(html_dir, f'<img src="{rel}">', tmp_path)
    assert _media_files(out) == []


def test_symlink_inside_html_dir_pointing_outside_is_not_copied(workspace, tmp_path):
    html_dir, secret = workspace
    link = html_dir / "link.png"
    link.symlink_to(secret)
    out = _convert(html_dir, '<img src="link.png">', tmp_path)
    assert _media_files(out) == []


def test_sibling_file_next_to_html_is_still_copied(workspace, tmp_path):
    html_dir, _ = workspace
    out = _convert(html_dir, '<img src="ok.png">', tmp_path)
    files = _media_files(out)
    assert len(files) == 1
    assert files[0].read_bytes() == SIBLING_BYTES


def test_guard_denies_everything_without_a_source_html():
    converter = HTML2MarkdownConverter(output_dir="/tmp/unused-f068")
    assert converter._is_local_media_allowed(Path("/etc/passwd")) is False
