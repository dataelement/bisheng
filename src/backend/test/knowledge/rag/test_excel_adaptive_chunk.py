"""Adaptive excel chunking: slice_length is an upper bound, not an exact count.

Drives the planner with in-memory DataFrames so the tests are hermetic and fast.
"""

import os
import tempfile

import pandas as pd
import pytest

from bisheng.common.constants.knowledge import KNOWLEDGE_MAX_CHUNK_CHARS
from bisheng.common.errcode.knowledge import KnowledgeExcelChunkMaxError
from bisheng.knowledge.rag.pipeline.loader.excel import ExcelLoader
from bisheng.knowledge.rag.pipeline.loader.utils.md_from_excel import (
    ExcelRowTooLongError,
    process_dataframe_to_markdown_files,
    render_markdown_row,
)

MAX_CHARS = KNOWLEDGE_MAX_CHUNK_CHARS


def _run(df, rows_per_markdown, append_header=True, num_header_rows=(0, 0), **kwargs):
    """Run the planner and return the chunk contents in emission order."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        process_dataframe_to_markdown_files(
            df,
            "0",
            list(num_header_rows),
            rows_per_markdown,
            tmp_dir,
            append_header=append_header,
            **kwargs,
        )
        names = sorted(one for one in os.listdir(tmp_dir) if one.endswith(".md"))
        return names, [open(os.path.join(tmp_dir, one), encoding="utf-8").read() for one in names]


def _data_lines(chunk: str, header_row_count: int) -> list[str]:
    """Strip the header block and the markdown separator from one chunk."""
    lines = [one for one in chunk.split("\n") if not one.startswith("|---")]
    return lines[header_row_count:]


def _simple_df(rows: int, cols: int = 3, cell: str = "v"):
    grid = [[f"h{c}" for c in range(cols)]]
    grid += [[f"{cell}{r}_{c}" for c in range(cols)] for r in range(rows)]
    return pd.DataFrame(grid)


def _long_text_df(data_rows: int = 11, cols: int = 10, text_len: int = 1500):
    """The shape that triggered the bug: short columns plus one long free-text column."""
    grid = [[f"col{c}" for c in range(cols)]]
    for r in range(data_rows):
        row = [f"c{r}_{c}" for c in range(cols)]
        row[cols - 1] = f"row{r}-" + ("长文本内容。" * (text_len // 6))
        grid.append(row)
    return pd.DataFrame(grid)


def test_max_chars_none_preserves_legacy_grouping():
    df = _simple_df(rows=25)
    names, chunks = _run(df, rows_per_markdown=10, max_chars=None)

    assert len(chunks) == 3
    assert [len(_data_lines(one, 1)) for one in chunks] == [10, 10, 5]
    # sorted() order must equal emission order -- ExcelLoader relies on it.
    assert names == sorted(names)


def test_under_limit_output_is_byte_identical():
    """Backward-compat invariant: a file that fits today must chunk exactly as before."""
    df = _simple_df(rows=25)
    _, legacy = _run(df, rows_per_markdown=10, max_chars=None)
    _, budgeted = _run(df, rows_per_markdown=10, max_chars=MAX_CHARS)

    assert budgeted == legacy


def test_long_free_text_rows_are_subdivided():
    df = _long_text_df()

    _, legacy = _run(df, rows_per_markdown=10, max_chars=None)
    assert max(len(one) for one in legacy) > MAX_CHARS, "fixture must exceed the limit today"

    _, chunks = _run(df, rows_per_markdown=10, max_chars=MAX_CHARS)

    assert all(len(one) <= MAX_CHARS for one in chunks)
    assert len(chunks) > len(legacy)

    # Row conservation: no data row lost, duplicated or reordered.
    recovered = [line for one in chunks for line in _data_lines(one, 1)]
    expected = [render_markdown_row(row) for row in df.values.tolist()[1:]]
    assert recovered == expected


def test_slice_length_acts_as_upper_bound():
    """A too-large slice_length no longer fails -- the budget caps it."""
    df = _long_text_df()
    _, chunks = _run(df, rows_per_markdown=100, max_chars=MAX_CHARS)

    assert all(len(one) <= MAX_CHARS for one in chunks)
    recovered = [line for one in chunks for line in _data_lines(one, 1)]
    assert recovered == [render_markdown_row(row) for row in df.values.tolist()[1:]]


def test_header_repeated_on_every_subchunk():
    df = _long_text_df()
    # Two header rows: sheet rows 1-2.
    _, chunks = _run(df, rows_per_markdown=10, num_header_rows=(0, 1), max_chars=MAX_CHARS)

    assert len(chunks) > 1
    header_lines = [render_markdown_row(row) for row in df.values.tolist()[:2]]
    for one in chunks:
        lines = one.split("\n")
        assert lines[0] == header_lines[0]
        assert lines[1].startswith("|---")
        assert lines[2] == header_lines[1]
        assert len(one) <= MAX_CHARS


def test_append_header_false_pseudo_header_per_subchunk():
    df = _long_text_df()
    _, chunks = _run(df, rows_per_markdown=10, append_header=False, max_chars=MAX_CHARS)

    assert len(chunks) > 1
    for one in chunks:
        lines = one.split("\n")
        assert lines[0].startswith("| ")
        assert lines[1].startswith("|---")
        assert len(one) <= MAX_CHARS

    # The pseudo-header row is real data and must not be dropped.
    recovered = [line for one in chunks for line in _data_lines(one, 0)]
    assert recovered == [render_markdown_row(row) for row in df.values.tolist()]


def test_single_row_over_limit_raises_without_splitter():
    grid = [["名称", "正文"], ["甲", "超长" * MAX_CHARS], ["乙", "短"]]
    df = pd.DataFrame(grid)

    with pytest.raises(ExcelRowTooLongError) as exc:
        _run(df, rows_per_markdown=10, max_chars=MAX_CHARS)

    # 1-based sheet row number, i.e. what the user sees in Excel.
    assert exc.value.row_number == 2
    assert exc.value.max_chars == MAX_CHARS


def test_single_row_over_limit_degrades_to_plain_text():
    body = "第一段内容。\n\n" + ("超长正文。" * 4000)
    grid = [["名称", "正文"], ["甲", body], ["乙", "短"]]
    df = pd.DataFrame(grid)

    def splitter(text: str, budget: int) -> list[str]:
        size = min(2000, budget)
        return [text[i : i + size] for i in range(0, len(text), size)]

    _, chunks = _run(df, rows_per_markdown=10, max_chars=MAX_CHARS, long_row_splitter=splitter)

    header_line = render_markdown_row(["名称", "正文"])
    degraded = [one for one in chunks if not one.split("\n")[-1].startswith("| 甲 |")]
    assert len(degraded) > 1, "the over-long row must yield several plain-text chunks"
    for one in degraded:
        assert one.startswith(header_line), "every fragment keeps the table header as prefix"
        assert "| 甲 |" not in one, "the over-long row is no longer rendered as a table row"

    # Column labels survive, and the full cell text is still covered.
    joined = "".join(degraded)
    assert "名称: 甲" in joined
    assert "正文: 第一段内容。" in joined

    # The short row is still a normal table chunk.
    assert any("| 乙 | 短 |" in one for one in chunks)


def test_chunk_filenames_sort_lexicographically_beyond_999():
    df = _simple_df(rows=1200, cols=2)
    names, _ = _run(df, rows_per_markdown=1, max_chars=None)

    assert len(names) == 1200
    assert names == sorted(names)


def _write_xlsx(path, grid):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in grid:
        ws.append(row)
    wb.save(path)


def test_excel_loader_end_to_end_chunk_index_is_sequential():
    df = _long_text_df()
    with tempfile.TemporaryDirectory() as tmp_dir:
        xlsx_path = os.path.join(tmp_dir, "sample.xlsx")
        _write_xlsx(xlsx_path, df.values.tolist())

        loader = ExcelLoader(
            file_path=xlsx_path,
            file_metadata={},
            file_extension="xlsx",
            tmp_dir=tmp_dir,
            header_rows=[0, 0],
            data_rows=10,
            append_header=True,
        )
        documents = loader.load()

    assert len(documents) > 1
    assert [one.metadata["chunk_index"] for one in documents] == list(range(len(documents)))
    assert all(len(one.page_content) <= KNOWLEDGE_MAX_CHUNK_CHARS for one in documents)


def test_excel_loader_degrades_over_long_row_instead_of_failing():
    grid = [
        ["名称", "正文"],
        ["甲", "超长正文。\n\n" + ("填充内容。" * 5000)],
        ["乙", "短"],
    ]
    with tempfile.TemporaryDirectory() as tmp_dir:
        xlsx_path = os.path.join(tmp_dir, "long_row.xlsx")
        _write_xlsx(xlsx_path, grid)

        loader = ExcelLoader(
            file_path=xlsx_path,
            file_metadata={},
            file_extension="xlsx",
            tmp_dir=tmp_dir,
            header_rows=[0, 0],
            data_rows=10,
            append_header=True,
        )
        documents = loader.load()

    assert len(documents) > 1
    assert all(len(one.page_content) <= KNOWLEDGE_MAX_CHUNK_CHARS for one in documents)
    assert any("名称: 甲" in one.page_content for one in documents)
    assert any("| 乙 | 短 |" in one.page_content for one in documents)


def test_excel_loader_chunk_size_is_clamped_to_the_budget():
    """The admin UI allows chunk_size > the hard limit; the degraded path must clamp it."""
    loader = ExcelLoader(
        file_path="unused.xlsx",
        file_metadata={},
        file_extension="xlsx",
        tmp_dir="/tmp",
        chunk_size=50000,
    )
    fragments = loader._split_long_row_text("正文。" * 20000, KNOWLEDGE_MAX_CHUNK_CHARS)

    assert fragments
    assert all(len(one) <= KNOWLEDGE_MAX_CHUNK_CHARS for one in fragments)


def test_excel_loader_splits_text_without_any_separator():
    """A long cell holding none of the configured separators must still break up."""
    loader = ExcelLoader(
        file_path="unused.xlsx",
        file_metadata={},
        file_extension="xlsx",
        tmp_dir="/tmp",
    )
    fragments = loader._split_long_row_text("x" * 25000, 5000)

    assert len(fragments) > 1
    assert all(len(one) <= 5000 for one in fragments)


def test_over_long_row_with_no_separator_still_fits_the_budget():
    """End-to-end: no separators anywhere, header prefix included in the budget."""
    grid = [["名称", "正文"], ["甲", "x" * 40000], ["乙", "短"]]
    with tempfile.TemporaryDirectory() as tmp_dir:
        xlsx_path = os.path.join(tmp_dir, "no_sep.xlsx")
        _write_xlsx(xlsx_path, grid)

        loader = ExcelLoader(
            file_path=xlsx_path,
            file_metadata={},
            file_extension="xlsx",
            tmp_dir=tmp_dir,
            header_rows=[0, 0],
            data_rows=10,
            append_header=True,
        )
        documents = loader.load()

    assert len(documents) > 1
    assert all(len(one.page_content) <= KNOWLEDGE_MAX_CHUNK_CHARS for one in documents)
    # The header prefix rides along on every degraded fragment.
    degraded = [one for one in documents if "| 乙 | 短 |" not in one.page_content]
    assert degraded
    assert all(one.page_content.startswith(render_markdown_row(["名称", "正文"])) for one in degraded)


def test_max_chunk_limit_is_centralized():
    loader = ExcelLoader(
        file_path="unused.xlsx",
        file_metadata={},
        file_extension="xlsx",
        tmp_dir="/tmp",
    )
    assert loader.max_chunk_limit == KNOWLEDGE_MAX_CHUNK_CHARS


def test_excel_chunk_max_error_is_still_the_defensive_net():
    """The loader-level check stays reachable if the budget math ever drifts."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        md_dir = os.path.join(tmp_dir, "chunk_md")
        os.makedirs(md_dir)
        with open(os.path.join(md_dir, "000_000000.md"), "w", encoding="utf-8") as f:
            f.write("x" * (KNOWLEDGE_MAX_CHUNK_CHARS + 1))

        loader = ExcelLoader(
            file_path=os.path.join(tmp_dir, "missing.xlsx"),
            file_metadata={},
            file_extension="xlsx",
            tmp_dir=tmp_dir,
        )
        # convert_file_to_markdown returns early for a missing input file, so the
        # pre-seeded oversized chunk is what the loader reads back.
        with pytest.raises(KnowledgeExcelChunkMaxError):
            loader.load()
