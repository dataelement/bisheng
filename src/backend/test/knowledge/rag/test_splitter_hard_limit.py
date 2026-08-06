"""Hard-split fallback for fragments no configured separator can break.

Regression cover for the ETL4LM path: its Table elements are markdown tables
whose rows can run thousands of characters with no ``\\n`` / ``。`` / ``.`` inside
(one observed row was 7820 chars across 601 cells). Such a fragment used to
survive ``ElemCharacterTextSplitter`` untouched and then fail the whole file at
``SplitterTransformer``'s max_chunk_limit check. PaddleOCR/MinerU never hit this
because they rewrite tables to per-row markdown before splitting.
"""

from langchain_core.documents import Document

from bisheng.common.constants.knowledge import KNOWLEDGE_MAX_CHUNK_CHARS
from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer

DEFAULT_SEPARATORS = ["\n\n", "\n", "。", "\\."]
CHUNK_SIZE = 1000


def _transformer(**kwargs) -> SplitterTransformer:
    params = {
        "separator": DEFAULT_SEPARATORS,
        "separator_rule": ["after"] * len(DEFAULT_SEPARATORS),
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": 0,
    }
    params.update(kwargs)
    return SplitterTransformer(**params)


def _wide_table_row(char_len: int) -> str:
    """A single markdown table row: no newline, no period, only ' | ' between cells."""
    cell = "呼气吸气当肺活化时乙醇消毒液与碘酒的混合物喷洒完毕后用酒精棉球擦拭"
    row = "|"
    while len(row) < char_len:
        row += f" {cell} |"
    return row


def test_oversized_separator_proof_fragment_is_split_instead_of_rejected():
    """The real failure: a >10000 char fragment with none of the default separators."""
    text = _wide_table_row(KNOWLEDGE_MAX_CHUNK_CHARS + 3000)
    assert "\n" not in text and "。" not in text and "." not in text

    chunks = _transformer().transform_documents([Document(page_content=text, metadata={})])

    assert len(chunks) > 1
    assert max(len(one.page_content) for one in chunks) <= CHUNK_SIZE
    # No text is dropped on the way through.
    assert "".join(one.page_content for one in chunks).replace(" ", "") == text.replace(" ", "")


def test_fragment_under_hard_limit_keeps_current_boundaries():
    """Zero-regression guard: below the hard limit nothing changes.

    A 3596-char unbreakable fragment is exactly what the reported document
    produces today; it must still come through as one chunk, or every stored
    document would re-chunk differently after this change.
    """
    text = _wide_table_row(3596)

    chunks = _transformer().transform_documents([Document(page_content=text, metadata={})])

    assert len(chunks) == 1
    assert chunks[0].page_content == text


def test_hard_split_respects_configured_chunk_size():
    text = _wide_table_row(KNOWLEDGE_MAX_CHUNK_CHARS + 500)

    chunks = _transformer(chunk_size=300).transform_documents([Document(page_content=text, metadata={})])

    assert max(len(one.page_content) for one in chunks) <= 300


def test_normal_text_splitting_is_untouched():
    """Ordinary prose must split exactly where the separators say, as before."""
    paragraph = "这是一段普通的中文正文内容用于验证切分行为没有发生变化。" * 60
    text = "\n\n".join([paragraph, paragraph])

    chunks = _transformer().transform_documents([Document(page_content=text, metadata={})])

    assert all(len(one.page_content) <= CHUNK_SIZE for one in chunks)
    # Every boundary still lands after a full sentence, i.e. the separator did the work.
    assert all(one.page_content.rstrip().endswith("。") for one in chunks)


def test_hard_split_chunks_still_resolve_bboxes():
    """chunk_bboxes come from text.find() in create_documents, which hard-split chunks keep."""
    text = _wide_table_row(KNOWLEDGE_MAX_CHUNK_CHARS + 2000)
    metadata = {
        "indexes": [[0, len(text)]],
        "bboxes": [[95, 390, 489, 430]],
        "pages": [95],
        "types": ["table"],
        "source": "wide_table.pdf",
    }

    chunks = _transformer().transform_documents([Document(page_content=text, metadata=metadata)])

    assert len(chunks) > 1
    for one in chunks:
        assert one.metadata["chunk_bboxes"], "hard-split chunk lost its bbox attribution"
        assert one.metadata["chunk_type"] == "table"
        assert one.metadata["page"] == 95


def test_empty_string_separator_does_not_raise_keyerror():
    """separator_rule is keyed by the caller's separators; '' must not blow up."""
    text = _wide_table_row(2000)

    chunks = _transformer(separator=[*DEFAULT_SEPARATORS, ""], separator_rule=["after"] * 5).transform_documents(
        [Document(page_content=text, metadata={})]
    )

    assert max(len(one.page_content) for one in chunks) <= CHUNK_SIZE
