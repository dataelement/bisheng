"""WorkspaceBackend.read / .aread report the read window (total lines, resume offset).

deepagents' ``read_file`` prints ``@@ lines A-B of T | next offset N @@`` above the
content, built only from the window fields the backend sets on ``ReadResult``. The
workspace backend used to return bare content, so a partial read looked like the
whole file: on 106 (2026-11-20, session a84724b8) a sub-agent read a report to line
498, never saw the financial appendix past it, and looped for 17 minutes.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from deepagents.middleware.filesystem import FilesystemMiddleware

from bisheng.linsight.domain.services.workspace_backend import _CHAR_PAGE_MIN_CHARS, WorkspaceBackend

REPORT = "output/report.md"
TOTAL = 600
TEXT = "\n".join(f"line {i}" for i in range(1, TOTAL + 1)) + "\n"


def _backend(tmp_path, files: dict[str, str]) -> WorkspaceBackend:
    minio = MagicMock()
    minio.bucket = "bisheng"
    backend = WorkspaceBackend(svid="sv-window", minio=minio, file_dir=str(tmp_path))
    for rel, text in files.items():
        backend._cache_write(rel, text.encode())
    return backend


@pytest.fixture
def backend(tmp_path):
    return _backend(tmp_path, {REPORT: TEXT})


def test_partial_read_carries_total_and_resume_offset(backend):
    result = backend.read("/" + REPORT, offset=300, limit=200)
    assert result.error is None
    assert (result.total_lines, result.start_line, result.end_line, result.next_offset) == (TOTAL, 301, 500, 500)
    assert result.file_data["content"].splitlines()[0] == "line 301"
    assert result.file_data["content"].splitlines()[-1] == "line 500"


async def test_aread_matches_read(backend):
    sync = backend.read("/" + REPORT, offset=300, limit=200)
    result = await backend.aread("/" + REPORT, offset=300, limit=200)
    assert result == sync


def test_last_page_has_no_resume_offset(backend):
    result = backend.read("/" + REPORT, offset=500, limit=200)
    assert (result.start_line, result.end_line, result.next_offset) == (501, TOTAL, None)


def test_offset_past_the_end_states_the_length(backend):
    # Used to return "", which the middleware reports as "File exists but has empty contents".
    result = backend.read("/" + REPORT, offset=TOTAL, limit=100)
    assert result.file_data is None
    assert f"({TOTAL} lines)" in result.error


def test_negative_offset_reads_from_the_start(backend):
    result = backend.read("/" + REPORT, offset=-5, limit=2)
    assert (result.start_line, result.end_line) == (1, 2)


def test_zero_limit_is_not_reported_as_an_empty_file(backend):
    result = backend.read("/" + REPORT, offset=0, limit=0)
    assert result.no_lines_requested
    assert result.total_lines is None


def test_blank_file_has_no_window(tmp_path):
    result = _backend(tmp_path, {"output/blank.md": "  \n\n"}).read("/output/blank.md")
    assert result.start_line is None and result.total_lines is None


def test_char_paged_file_keeps_its_own_notice_and_no_line_window(tmp_path):
    one_line = "x" * (_CHAR_PAGE_MIN_CHARS + 5000)
    result = _backend(tmp_path, {"large_tool_results/a": one_line}).read("/large_tool_results/a", offset=1, limit=1)
    assert "paginated by CHARACTER" in result.file_data["content"]
    assert result.start_line is None and result.total_lines is None


async def test_read_file_tool_shows_total_and_next_offset(backend):
    """The model-visible contract, through deepagents' real read_file tool."""
    tool = next(t for t in FilesystemMiddleware(backend=backend).tools if t.name == "read_file")
    message = await tool.coroutine(
        file_path="/" + REPORT, runtime=SimpleNamespace(tool_call_id="call-1"), offset=300, limit=200
    )
    header = message.content.splitlines()[0]
    assert header == f"@@ lines 301-500 of {TOTAL} | next offset 500 @@"

    last = await tool.coroutine(
        file_path="/" + REPORT, runtime=SimpleNamespace(tool_call_id="call-2"), offset=500, limit=200
    )
    assert last.content.splitlines()[0] == f"@@ lines 501-{TOTAL} of {TOTAL} @@"
