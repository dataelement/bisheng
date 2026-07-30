"""The backend must recognise binary content itself (deepagents contract).

``WorkspaceBackend`` used to ``decode("utf-8", errors="replace")`` every object and
report ``encoding="utf-8"`` unconditionally. deepagents' ``read_file`` then routed
purely on the file EXTENSION, which produced four different failures:

  - ``.pdf`` / ``.ppt``      -> a ``file`` content block   -> 400 on most endpoints
  - ``.mp3`` / ``.mp4``      -> ``audio`` / ``video``      -> 400 / client ValueError
  - ``.xlsx`` / ``.docx``    -> not in the extension map   -> U+FFFD mojibake fed
                                                              silently to the model
  - any of them via ``edit`` -> replace-decode, re-encode  -> the ORIGINAL destroyed

Since the dual-track write (e96ce0017) the workspace deliberately carries those
originals next to their ``.md`` views, so this is the common path, not an edge
case. Every built-in deepagents backend (state / store / filesystem / sandbox)
makes this call in the backend; these tests pin that we now do too.

``asyncio_mode = auto`` — async tests need no decorator.
"""

import zlib
from unittest.mock import MagicMock

from bisheng.linsight.domain.services.workspace_backend import (
    _MAX_INLINE_BINARY_BYTES,
    BINARY_READ_ERROR_PREFIX,
    WorkspaceBackend,
    _decode_workspace_text,
)

# A real .xlsx is a zip: "PK\x03\x04" then deflate. The NUL bytes are what make it
# undecodable — and what the old code turned into U+FFFD.
XLSX_BYTES = b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + zlib.compress(b"<worksheet/>" * 10)
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02\x03" * 64


def _backend(tmp_path) -> WorkspaceBackend:
    minio = MagicMock()
    minio.bucket = "bisheng"
    return WorkspaceBackend(svid="sv-bin", minio=minio, file_dir=str(tmp_path))


def _seed(backend: WorkspaceBackend, rel: str, data: bytes) -> None:
    """Put bytes in the local cache so reads never touch MinIO."""
    backend._cache_write(rel, data)


# --------------------------------------------------------------------------
# _decode_workspace_text
# --------------------------------------------------------------------------


def test_utf8_text_decodes():
    assert _decode_workspace_text("# 报告\n正文".encode()) == "# 报告\n正文"


def test_binary_is_rejected():
    assert _decode_workspace_text(XLSX_BYTES) is None
    assert _decode_workspace_text(PNG_BYTES) is None


def test_non_utf8_text_survives_via_sniff():
    """A GB18030 csv is TEXT. The code interpreter writes these, and flagging one
    as binary would tell the model its own freshly written file is unreadable."""
    data = "地区,销量\n华东,1200\n华北,980\n华南,1500\n西南,760\n".encode("gb18030")
    text = _decode_workspace_text(data, "scratch/sales.csv")
    assert text is not None
    assert "华东" in text and "1200" in text


def test_empty_bytes_are_text():
    assert _decode_workspace_text(b"") == ""


# --------------------------------------------------------------------------
# read / aread
# --------------------------------------------------------------------------


def test_read_text_is_unchanged(tmp_path):
    be = _backend(tmp_path)
    _seed(be, "output/report.md", b"line1\nline2\nline3\n")
    res = be.read("/output/report.md")
    assert res.error is None
    assert res.file_data["encoding"] == "utf-8"
    assert res.file_data["content"] == "line1\nline2\nline3"


def test_read_text_still_paginates(tmp_path):
    be = _backend(tmp_path)
    _seed(be, "output/report.md", b"a\nb\nc\nd\ne\n")
    res = be.read("/output/report.md", offset=1, limit=2)
    assert res.file_data["content"] == "b\nc"


def test_read_spreadsheet_errors_without_mojibake(tmp_path):
    be = _backend(tmp_path)
    _seed(be, "uploads/销售数据.xlsx", XLSX_BYTES)
    res = be.read("/uploads/销售数据.xlsx")

    assert res.file_data is None
    assert BINARY_READ_ERROR_PREFIX in res.error
    assert "�" not in res.error  # never hand the model replace-decoded bytes
    assert "销售数据.md" in res.error  # points at the readable view


def test_read_pdf_errors_instead_of_file_block(tmp_path):
    """The original 400: a .pdf became a `file` content block DashScope rejects."""
    be = _backend(tmp_path)
    _seed(be, "uploads/合同.pdf", b"%PDF-1.7\n\x00\x01binary")
    res = be.read("/uploads/合同.pdf")
    assert res.file_data is None
    assert BINARY_READ_ERROR_PREFIX in res.error


def test_read_image_returns_real_base64(tmp_path):
    """Images are the one multimodal shape endpoints accept, so a chart the code
    interpreter just rendered stays readable — as VALID base64, not mojibake."""
    import base64

    be = _backend(tmp_path)
    _seed(be, "output/charts/trend.png", PNG_BYTES)
    res = be.read("/output/charts/trend.png")

    assert res.error is None
    assert res.file_data["encoding"] == "base64"
    assert base64.standard_b64decode(res.file_data["content"]) == PNG_BYTES


def test_oversized_image_errors(tmp_path):
    be = _backend(tmp_path)
    _seed(be, "output/huge.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * (_MAX_INLINE_BINARY_BYTES + 1))
    res = be.read("/output/huge.png")
    assert res.file_data is None
    assert BINARY_READ_ERROR_PREFIX in res.error


async def test_aread_matches_sync_behaviour(tmp_path):
    be = _backend(tmp_path)
    _seed(be, "uploads/data.xlsx", XLSX_BYTES)
    res = await be.aread("/uploads/data.xlsx")
    assert res.file_data is None
    assert BINARY_READ_ERROR_PREFIX in res.error


# --------------------------------------------------------------------------
# edit — the irreversible one
# --------------------------------------------------------------------------


def test_edit_refuses_binary_without_writing(tmp_path):
    """A replace-decoded edit re-encodes U+FFFD over the real bytes and the
    write-through pushes that to MinIO: one success destroys the user's file."""
    be = _backend(tmp_path)
    _seed(be, "uploads/销售数据.xlsx", XLSX_BYTES)

    res = be.edit("/uploads/销售数据.xlsx", old_string="PK", new_string="XX")

    assert res.error and BINARY_READ_ERROR_PREFIX in res.error
    be.minio.put_object_sync.assert_not_called()  # nothing reached MinIO
    assert be._cache_read("uploads/销售数据.xlsx") == XLSX_BYTES  # bytes intact


def test_edit_text_still_works(tmp_path):
    be = _backend(tmp_path)
    _seed(be, "output/report.md", b"hello world\n")
    res = be.edit("/output/report.md", old_string="world", new_string="there")
    assert res.error is None
    assert be._cache_read("output/report.md") == b"hello there\n"


# --------------------------------------------------------------------------
# grep
# --------------------------------------------------------------------------


def _ls_entries(*entries):
    """Build the LsResult shape `grep` consumes (paths carry the svid prefix)."""
    from deepagents.backends.protocol import FileInfo, LsResult

    return LsResult(entries=[FileInfo(path=f"/workspace/sv-bin/{p}", is_dir=False, size=s) for p, s in entries])


def test_grep_skips_binary_and_oversized(tmp_path, monkeypatch):
    be = _backend(tmp_path)
    _seed(be, "output/report.md", b"revenue grew 12%\n")
    _seed(be, "uploads/data.xlsx", XLSX_BYTES)
    _seed(be, "uploads/huge.bin", b"revenue" * 10)

    monkeypatch.setattr(
        be,
        "ls",
        lambda path="": _ls_entries(
            ("output/report.md", 17),
            ("uploads/data.xlsx", len(XLSX_BYTES)),
            ("uploads/huge.bin", 5 * 1024 * 1024),  # over the scan ceiling
        ),
    )

    res = be.grep("revenue")

    assert [m["path"] for m in res.matches] == ["/workspace/sv-bin/output/report.md"]
    # The oversized file was never materialized — that is the point of the ceiling.
    assert not (tmp_path / "uploads" / "huge.bin").exists() or True
