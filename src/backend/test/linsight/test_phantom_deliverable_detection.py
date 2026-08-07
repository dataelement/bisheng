"""Phantom deliverables: detect the model's false claims, never repair them.

A model that signs off with 「已保存为 详细分析报告.md」 having never called
write_file has a defect the kernel prompt already forbids (agent_factory §3 and
§风格). An earlier revision of ``linsight.domain.utils`` answered that claim by
CREATING the file — which made the run look healthy, silently invented a document
nobody asked for, and left no way to measure how often it happens.

These tests pin the replacement: the claim is detected and reported, the file is
not fabricated. Most of them are false-positive guards, because that is where the
design is load-bearing — an answer legitimately cites external URLs, quotes back
the user's own uploads, and points at scratch notes, and none of those are claims
about this run's deliverables. ``select_deliverables`` excludes uploads/ and
scratch/ outright, so counting them would make the detector fire on nearly every
turn that reads a user file.
"""

from unittest.mock import AsyncMock, patch

from bisheng.linsight.domain.utils import (
    FALLBACK_REPORT_NAME,
    build_fallback_report_file,
    detect_phantom_deliverables,
    extract_claimed_deliverable_filenames,
)

# --- detection --------------------------------------------------------------


def test_detects_a_claimed_file_that_was_never_written():
    assert detect_phantom_deliverables("已保存为 output/详细分析报告.md", []) == ["详细分析报告.md"]


def test_detects_only_the_extra_name_when_some_files_are_real():
    """The shape a fabricating fallback could never surface: it only ever ran
    when the file list was empty, so 'wrote a.md, claimed a.md AND b.md' passed
    silently."""
    answer = "已生成 [a](output/a.md) 和 [b](output/b.md)"
    assert detect_phantom_deliverables(answer, [{"file_name": "a.md"}]) == ["b.md"]


def test_a_real_deliverable_is_not_flagged():
    assert detect_phantom_deliverables("已保存为 output/报告.md", [{"file_name": "报告.md"}]) == []


def test_matches_case_insensitively():
    """A case-only mismatch is a resolver problem, not evidence the model lied —
    and a false accusation is worse than a miss in something whose only job is
    diagnosis."""
    assert detect_phantom_deliverables("已保存为 Report.MD", [{"file_name": "report.md"}]) == []


def test_detects_a_claimed_docx_export():
    """Steps 3c/3d make export_docx/export_pdf the closing action, so a run that
    exhausts its turn budget stops exactly there. A .md-only detector would miss
    the likeliest claim of all."""
    assert detect_phantom_deliverables("已导出 报告.docx，请查收。", []) == ["报告.docx"]


def test_empty_answer_and_empty_file_list_are_quiet():
    assert detect_phantom_deliverables("", None) == []
    assert detect_phantom_deliverables("你好！", []) == []


# --- false-positive guards --------------------------------------------------


def test_ignores_an_external_url_ending_in_a_deliverable_extension():
    assert (
        extract_claimed_deliverable_filenames("参考 [规范](https://raw.githubusercontent.com/a/b/README.md) 的写法。")
        == []
    )
    assert extract_claimed_deliverable_filenames("见 [白皮书](https://example.com/docs/wp.pdf)。") == []


def test_ignores_an_uploaded_source_reference():
    """The link TEXT here looks like a bare filename; only the target reveals the
    zone. They must be judged as a pair."""
    assert extract_claimed_deliverable_filenames("根据 [briefing.md](uploads/briefing.md) 分析如下。") == []


def test_ignores_a_scratch_reference():
    assert extract_claimed_deliverable_filenames("笔记见 [notes.md](scratch/notes.md)。") == []


def test_ignores_a_bare_mention_without_a_save_claim():
    """A plan is not a claim. The save verb is what makes it one."""
    assert extract_claimed_deliverable_filenames("可以整理成 总结.md 交给团队。") == []
    assert extract_claimed_deliverable_filenames("依据《运维手册.md》第三章。") == []


def test_a_bare_filename_link_is_a_claim():
    """No zone prefix means the delivery contract reads it as output/."""
    assert extract_claimed_deliverable_filenames("详见 [报告](报告.md)") == ["报告.md"]


# --- the F035 fallback body -------------------------------------------------
# Never had a test: all three call-site tests monkeypatch build_fallback_report_file,
# which is how it could be rewritten into a multi-file loop with the suite green.


class _FakeMinio:
    def __init__(self) -> None:
        self.bucket = "bisheng"
        self.store: dict[tuple[str, str], str] = {}

    async def put_object(self, *, bucket_name=None, object_name, file, **kwargs):
        self.store[(bucket_name or self.bucket, object_name)] = file


async def test_fallback_writes_exactly_one_verbatim_report(tmp_path):
    """One file, the fixed name, the answer character for character.

    Including any 交付物 list the model wrote: quietly editing the model's false
    claim out of the artifact is the same masking in a smaller costume.
    """
    answer = "分析结论如下。\n\n### 交付物\n1. [详细分析报告](output/详细分析报告.md)"
    session = type("S", (), {"id": "sv-1"})()
    fake_minio = _FakeMinio()

    with patch("bisheng.linsight.domain.utils.get_minio_storage", new=AsyncMock(return_value=fake_minio)):
        files = await build_fallback_report_file(session_model=session, answer=answer, file_dir=str(tmp_path))

    assert len(files) == 1
    assert files[0]["file_name"] == FALLBACK_REPORT_NAME
    assert (tmp_path / "output" / FALLBACK_REPORT_NAME).read_text(encoding="utf-8") == answer
    # ASCII-only object key: a non-ASCII key breaks presigned signatures on some
    # S3-compatible backends (Huawei OBS -> 403). Also untested until now.
    assert files[0]["file_url"].startswith("linsight/final_result/sv-1/")
    assert files[0]["file_url"].endswith(".md")
    assert files[0]["file_url"].split("/")[-1][:-3].isalnum()


async def test_fallback_returns_nothing_for_an_empty_answer(tmp_path):
    session = type("S", (), {"id": "sv-2"})()
    assert await build_fallback_report_file(session_model=session, answer="  ", file_dir=str(tmp_path)) == []
