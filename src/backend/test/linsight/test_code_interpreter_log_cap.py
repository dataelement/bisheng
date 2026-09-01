"""Success-path log capping in the code interpreter.

The failure path has had a cap since it was written; the SUCCESS path had none, and
that is what started the 2026-08-14 incident: a 112744-byte result crossed deepagents'
eviction threshold, got replaced by a preview that (because ToolNode json.dumps'es the
dict into ONE line) showed only its first 1000 characters, and the model — unable to
see file_list or anything past the opening — re-sent the identical script 79 times.

Capping keeps the output INSIDE the context instead of behind a pointer the model does
not follow. These tests pin the three properties that make that safe: both ends
survive, the advisory survives, and ordinary output is untouched.

``asyncio_mode = auto`` — async tests need no decorator.
"""

import json

from bisheng_langchain.gpts.tools.code_interpreter.base_executor import (
    MAX_SUCCESS_LOG_CHARS,
    clip_middle,
)


def _oversized(n=200_000):
    return "HEAD-MARKER\n" + ("x" * n) + "\nTAIL-MARKER"


# --------------------------------------------------------------------------- clip_middle


def test_short_log_is_byte_identical():
    """Ordinary runs must not change at all — measured p90 is ~8000 chars."""
    log = "\n".join(f"row {i}" for i in range(200))
    assert clip_middle(log) == log


def test_exactly_at_limit_is_untouched():
    log = "y" * MAX_SUCCESS_LOG_CHARS
    assert clip_middle(log) == log


def test_both_ends_survive():
    """Unlike the failure path's ``_tail``, the head must survive: for a succeeding
    run it holds what the script printed, while the tail holds the advisories."""
    out = clip_middle(_oversized())
    assert out.startswith("HEAD-MARKER")
    assert out.endswith("TAIL-MARKER")


def test_omission_is_stated_with_a_count_and_a_way_forward():
    out = clip_middle(_oversized())
    omitted = len(_oversized()) - MAX_SUCCESS_LOG_CHARS
    assert str(omitted) in out
    # Naming the cause is the point: a bare truncation reads as an infrastructure
    # hiccup and invites a verbatim retry (same lesson as TIMEOUT_MSG in this package).
    assert "Re-running this code will NOT return more" in out
    assert "scratch/" in out


def test_clipped_length_is_bounded():
    out = clip_middle(_oversized())
    assert len(out) <= MAX_SUCCESS_LOG_CHARS + 400  # payload + the notice itself


# ------------------------------------------------------- the reason the cap exists


def test_capped_result_stays_below_the_deepagents_eviction_threshold():
    """THE regression pin.

    Reads the threshold from deepagents rather than hardcoding it, so this goes red
    if upstream lowers its default or if someone raises MAX_SUCCESS_LOG_CHARS past
    what the eviction path tolerates. Serialization mirrors langgraph's ToolNode.
    """
    from inspect import signature

    from deepagents.middleware.filesystem import NUM_CHARS_PER_TOKEN, FilesystemMiddleware

    eviction_default = signature(FilesystemMiddleware.__init__).parameters["tool_token_limit_before_evict"].default
    result = {
        "exitcode": 0,
        "log": clip_middle(_oversized()),
        # file_list is never clipped, so budget for realistic MinIO URLs too.
        "file_list": [f"http://minio.local/bisheng/workspace/{'a' * 32}/output/chart{i}.png" for i in range(20)],
    }
    serialized = json.dumps(result, ensure_ascii=False)
    assert len(serialized) < NUM_CHARS_PER_TOKEN * eviction_default


def test_uncapped_result_would_have_been_evicted():
    """Proves the test above is actually load-bearing rather than trivially true."""
    from inspect import signature

    from deepagents.middleware.filesystem import NUM_CHARS_PER_TOKEN, FilesystemMiddleware

    eviction_default = signature(FilesystemMiddleware.__init__).parameters["tool_token_limit_before_evict"].default
    raw = json.dumps({"exitcode": 0, "log": _oversized(), "file_list": []}, ensure_ascii=False)
    assert len(raw) > NUM_CHARS_PER_TOKEN * eviction_default


def test_json_dumps_makes_the_result_a_single_line():
    """Pins the mechanism that made the upstream preview useless: newlines in the log
    become literal ``\\n``, so the whole payload is one line and the head/tail preview
    degrades to the first 1000 characters."""
    serialized = json.dumps({"exitcode": 0, "log": "a\nb\nc"}, ensure_ascii=False)
    assert len(serialized.splitlines()) == 1
