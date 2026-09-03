"""``glob`` must match the patterns we ourselves put in the prompt.

The folder-upload guidance (``workbench_impl.prepare_file_list``) tells the model,
verbatim and twice — once in the pointer header, once as the closing line of the
>40-file directory overview — to locate files with::

    glob（如 "/uploads/**/*.xlsx"）

That exact spelling used to return zero matches, for two independent reasons:

1. ``ls`` reports workspace paths with a leading slash (``/uploads/a/b.csv``) but
   matching runs against the workspace-relative object key (``uploads/a/b.csv``),
   and ``fnmatch`` is literal about that first character. So every absolute
   pattern — the only kind the prompt teaches — missed everything.
2. ``fnmatch`` has no ``**``: it is just a ``*`` that crosses ``/``, so
   ``uploads/**/*.csv`` requires at least one intermediate directory and skips a
   file sitting directly in ``uploads/``.

The failure mode is the worst kind: a silent empty result on a large folder,
where the overview block is the model's ONLY route to individual file names. The
same prompt then says 不要假设文件不存在 — which is precisely what an empty glob
invites. ``grep(glob=...)`` shares the comparison and so shared the bug.
"""

from __future__ import annotations

import tempfile

import pytest

from bisheng.linsight.domain.services.workspace_backend import WORKSPACE_PREFIX, WorkspaceBackend
from test.linsight.test_workspace_backend import FakeMinioStorage

TREE = [
    "uploads/年报/2024/Q1.csv",
    "uploads/年报/2024/Q2.csv",
    "uploads/年报/notes.txt",
    "uploads/附件/Q1.csv",
    "uploads/top.csv",  # directly under uploads/, no intermediate directory
    "output/report.md",
]


@pytest.fixture()
def backend():
    minio = FakeMinioStorage()
    for rel in TREE:
        minio.store[(minio.bucket, f"{WORKSPACE_PREFIX}/sv1/{rel}")] = b"name,amount\nalpha,1\n"
    with tempfile.TemporaryDirectory() as d:
        yield WorkspaceBackend(svid="sv1", minio=minio, file_dir=d)


def _paths(result) -> set[str]:
    return {m["path"] for m in (result.matches or [])}


# ---------------------------------------------------------------------------
# The pattern the prompt actually teaches
# ---------------------------------------------------------------------------
def test_absolute_pattern_from_the_prompt_matches(backend):
    """REGRESSION: `/uploads/**/*.csv` returned 0 matches, so a model that
    followed the folder-upload guidance concluded the files were not there."""
    got = _paths(backend.glob("/uploads/**/*.csv"))

    assert "/uploads/年报/2024/Q1.csv" in got
    assert "/uploads/附件/Q1.csv" in got
    # ** must span zero directories too, or a file sitting at the folder root is
    # invisible to the one pattern the user was told finds everything.
    assert "/uploads/top.csv" in got
    assert "/output/report.md" not in got


def test_absolute_and_relative_spellings_agree(backend):
    assert _paths(backend.glob("/uploads/**/*.csv")) == _paths(backend.glob("uploads/**/*.csv"))


def test_absolute_pattern_without_a_wildcard_directory(backend):
    """`/output/*.md` is the shape the code-interpreter guidance produces."""
    assert _paths(backend.glob("/output/*.md")) == {"/output/report.md"}


def test_bare_extension_pattern_still_matches_by_basename(backend):
    got = _paths(backend.glob("*.csv"))
    assert "/uploads/年报/2024/Q1.csv" in got
    assert "/uploads/top.csv" in got


def test_a_pattern_that_matches_nothing_still_matches_nothing(backend):
    assert _paths(backend.glob("/uploads/**/*.xlsx")) == set()
    assert _paths(backend.glob("/nope/**/*.csv")) == set()


# ---------------------------------------------------------------------------
# grep shares the comparison, and shared the bug
# ---------------------------------------------------------------------------
def test_grep_glob_filter_accepts_an_absolute_pattern(backend):
    res = backend.grep("alpha", glob="/uploads/**/*.csv")

    assert res.error is None
    hit_paths = {m.path if hasattr(m, "path") else m["path"] for m in (res.matches or [])}
    assert "/uploads/年报/2024/Q1.csv" in hit_paths
    assert "/output/report.md" not in hit_paths


def test_grep_without_a_glob_is_unfiltered(backend):
    res = backend.grep("alpha")
    assert res.error is None
    hit_paths = {m.path if hasattr(m, "path") else m["path"] for m in (res.matches or [])}
    assert "/output/report.md" in hit_paths


# ---------------------------------------------------------------------------
# The pattern-normalisation helper on its own
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("/uploads/**/*.csv", ("uploads/**/*.csv", "uploads/*.csv")),
        ("uploads/**/*.csv", ("uploads/**/*.csv", "uploads/*.csv")),
        ("/output/*.md", ("output/*.md",)),
        ("*.csv", ("*.csv",)),
        ("/", ()),
        ("", ()),
    ],
)
def test_glob_pattern_candidates(pattern, expected):
    assert WorkspaceBackend._glob_patterns(pattern) == expected
