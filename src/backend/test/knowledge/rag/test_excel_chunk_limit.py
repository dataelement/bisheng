from pathlib import Path

import pandas as pd

from bisheng.knowledge.rag.pipeline.loader.utils.md_from_excel import (
    process_dataframe_to_markdown_files,
)


def _read_chunks(output_dir: Path) -> list[str]:
    return [path.read_text(encoding="utf-8") for path in sorted(output_dir.glob("*.md"))]


def test_excel_chunks_reduce_rows_to_respect_character_limit(tmp_path):
    dataframe = pd.DataFrame([
        ["name", "description"],
        ["row-1", "a" * 45],
        ["row-2", "b" * 45],
        ["row-3", "c" * 45],
    ])

    process_dataframe_to_markdown_files(
        dataframe,
        sheet_index="0",
        num_header_rows=[0, 0],
        rows_per_markdown=10,
        output_dir=tmp_path,
        append_header=True,
        max_chunk_chars=110,
    )

    chunks = _read_chunks(tmp_path)
    assert len(chunks) == 3
    assert all(len(chunk) <= 110 for chunk in chunks)
    assert all("name" in chunk and "description" in chunk for chunk in chunks)
    assert sum(chunk.count("row-") for chunk in chunks) == 3


def test_excel_oversized_single_row_uses_character_fallback(tmp_path):
    dataframe = pd.DataFrame([
        ["name", "description"],
        ["row-1", "x" * 250],
    ])

    process_dataframe_to_markdown_files(
        dataframe,
        sheet_index="0",
        num_header_rows=[0, 0],
        rows_per_markdown=10,
        output_dir=tmp_path,
        append_header=True,
        max_chunk_chars=100,
    )

    chunks = _read_chunks(tmp_path)
    assert len(chunks) >= 3
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert "".join(chunks).count("x") == 250
