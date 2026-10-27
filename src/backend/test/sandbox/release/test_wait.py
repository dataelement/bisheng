"""Continue must not treat the first history growth as the new round."""

from test.sandbox.release.client import (
    _finished_code_calls,
    _task_snapshot,
    continue_round_done,
    followup_ready,
)
from test.sandbox.release.parse import offload_from_text


def _task(history, status="success"):
    return [{"id": "task-1", "status": status, "history": history}]


def _code(call_id, amounts):
    return {
        "name": "bisheng_code_interpreter",
        "status": "end",
        "call_id": call_id,
        "output": {"exitcode": 0, "log": "ok", "file_list": [amounts]},
    }


def test_continue_waits_for_the_new_code_call():
    first = _task([_code("round-1", "1,2,3")])
    baseline = _task_snapshot(first)
    codes = _finished_code_calls(first)

    grown = _task([_code("round-1", "1,2,3"), {"name": "write_file", "status": "end", "output": "updated"}])
    done, stable = followup_ready(grown, baseline=baseline, previous_codes=codes, was_waiting=False, stable=None)
    assert done is False

    second = _task([_code("round-1", "1,2,3"), _code("round-2", "2,4,6")])
    done, stable = followup_ready(second, baseline=baseline, previous_codes=codes, was_waiting=False, stable=stable)
    assert done is False
    done, _stable = followup_ready(second, baseline=baseline, previous_codes=codes, was_waiting=False, stable=stable)
    assert done is True


def test_offload_notice_reads_preview_ends():
    preview = "\n".join(
        [
            "Tool result too large, the result of this tool call call-1 was saved in the filesystem at this path: /large_tool_results/call-1",
            "",
            "     1\t第一行",
            "     2\t第二行",
            "... [6 lines truncated] ...",
            "     9\t倒数第二行",
            "    10\t最后一行",
        ]
    )
    notice = offload_from_text(preview)
    assert notice == {
        "path": "large_tool_results/call-1",
        "first": "第一行",
        "last": "最后一行",
        "count": 10,
    }
    assert offload_from_text("短结果，没有转存") is None


def test_failed_retry_does_not_finish_the_round():
    first = _task_snapshot(_task([_code("round-1", "1,2,3")]))
    retrying = _task_snapshot(_task([_code("round-1", "1,2,3"), _code("retry", "fail")]))
    assert continue_round_done("in_progress", retrying, first) is False
    assert continue_round_done("completed", first, first) is False
    assert continue_round_done("completed", retrying, first) is True


def test_unchanged_success_is_still_the_previous_round():
    first = _task([_code("round-1", "1,2,3")])
    done, stable = followup_ready(
        first,
        baseline=_task_snapshot(first),
        previous_codes=_finished_code_calls(first),
        was_waiting=False,
        stable=None,
    )
    assert done is False
    assert stable is None
