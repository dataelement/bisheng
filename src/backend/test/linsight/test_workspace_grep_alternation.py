"""Workspace ``grep`` treats ``|`` as keyword alternation, everything else literally.

Models keep writing ``A|B|C`` to search several keywords at once. On 106 (10-29)
5 of 7 greps in one task-mode session came back "No matches" that way although
every keyword was in the file, and each miss cost a model round. These tests pin
the rule: split on ``|`` unless a segment is blank, and always keep the whole
pattern as a literal term so nothing the old literal match found is lost.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from unittest.mock import MagicMock

from deepagents.backends.protocol import FileInfo, LsResult

from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend, _grep_terms

REPORT = "\n".join(
    [
        "公司主要从事核电运营业务。",
        "营业总收入基本来自于售电收入。",
        "| 操作id | 名称 |",
        "a || b",
        "price (USD) 3.5",
        "无关的一行",
    ]
)


def _backend(tmp_path) -> WorkspaceBackend:
    minio = MagicMock()
    minio.bucket = "bisheng"
    be = WorkspaceBackend(svid="sv-grep", minio=minio, file_dir=str(tmp_path))
    data = REPORT.encode()
    be._cache_write("uploads/report.md", data)
    be.ls = lambda path="": LsResult(
        entries=[FileInfo(path="/workspace/sv-grep/uploads/report.md", is_dir=False, size=len(data))]
    )
    return be


def _lines(res) -> list[int]:
    assert res.error is None
    return [m["line"] for m in res.matches]


# --------------------------------------------------------------------------
# _grep_terms
# --------------------------------------------------------------------------


def test_terms_plain_pattern_is_one_literal():
    assert _grep_terms("营业收入") == ("营业收入",)


def test_terms_split_on_pipe_keep_whole_pattern_first():
    assert _grep_terms("主要业务|主要从事|核电运营") == (
        "主要业务|主要从事|核电运营",
        "主要业务",
        "主要从事",
        "核电运营",
    )


def test_terms_strip_spaces_and_dedupe():
    assert _grep_terms("A | B|A") == ("A | B|A", "A", "B")


def test_terms_blank_segment_means_literal_pipe():
    assert _grep_terms("| 操作id |") == ("| 操作id |",)
    assert _grep_terms("a || b") == ("a || b",)
    assert _grep_terms("A|") == ("A|",)
    assert _grep_terms("A| |B") == ("A| |B",)


# --------------------------------------------------------------------------
# grep / agrep
# --------------------------------------------------------------------------


def test_grep_multiple_keywords_any_hit(tmp_path):
    be = _backend(tmp_path)
    # The exact pattern from the 106 session: no line holds it verbatim, but two
    # of its keywords are present.
    assert _lines(be.grep("主要业务|主要从事|核电运营")) == [1]
    assert _lines(be.grep("营业总收入|售电收入|核电业务")) == [2]
    assert _lines(be.grep("核电运营|售电收入")) == [1, 2]


def test_grep_no_keyword_present_still_no_match(tmp_path):
    be = _backend(tmp_path)
    assert _lines(be.grep("无受限资产|无对外担保")) == []


def test_grep_literal_pipe_whole_pattern(tmp_path):
    be = _backend(tmp_path)
    # Blank segments: the pipe is part of the text being searched.
    assert _lines(be.grep("a || b")) == [4]


def test_grep_markdown_table_row(tmp_path):
    be = _backend(tmp_path)
    assert _lines(be.grep("| 操作id |")) == [3]
    # Without blank segments the whole row still matches literally, and the
    # keyword split adds nothing beyond lines that hold one of the cells.
    assert _lines(be.grep("操作id | 名称")) == [3]


def test_grep_blank_segment_does_not_match_everything(tmp_path):
    be = _backend(tmp_path)
    # Splitting "核电|" would yield "" — a term that is in every line.
    assert _lines(be.grep("核电|")) == []


def test_grep_other_regex_chars_stay_literal(tmp_path):
    be = _backend(tmp_path)
    assert _lines(be.grep("price (USD) 3.5")) == [5]
    assert _lines(be.grep("营业.*收入")) == []


async def test_agrep_same_rule(tmp_path):
    be = _backend(tmp_path)
    assert _lines(await be.agrep("主要业务|主要从事|核电运营")) == [1]
    assert _lines(await be.agrep("| 操作id |")) == [3]
