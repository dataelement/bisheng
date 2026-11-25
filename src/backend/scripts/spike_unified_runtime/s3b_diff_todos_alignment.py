"""S3 (alignment half): does `_diff_todos` keep task ids stable when a user edits the plan?

Feeds the production `StreamEventMapper._diff_todos` a first plan and then four
kinds of user-driven rewrites, and reports which original task ids survive on
the row they belong to. A wrong alignment means the task panel shows the wrong
status on the wrong row after the user changes the plan mid-run.

Usage (from src/backend/, with the backend venv):
    .venv/bin/python scripts/spike_unified_runtime/s3b_diff_todos_alignment.py
"""

from __future__ import annotations

import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.linsight.domain.services import stream_event_mapper as sem  # noqa: E402

BASE = [
    {"content": "1. 收集资料", "status": "completed"},
    {"content": "2. 写报告", "status": "in_progress"},
    {"content": "3. 校对", "status": "pending"},
]

CASES = {
    "reword_one": [
        {"content": "1. 收集资料", "status": "completed"},
        {"content": "2. 写 PPT", "status": "in_progress"},
        {"content": "3. 校对", "status": "pending"},
    ],
    "append_one": [*BASE, {"content": "4. 发邮件", "status": "pending"}],
    "insert_in_middle": [
        BASE[0],
        {"content": "1.5 访谈用户", "status": "in_progress"},
        {"content": "2. 写报告", "status": "pending"},
        BASE[2],
    ],
    "delete_middle": [BASE[0], BASE[2]],
}


def new_mapper():
    return sem.StreamEventMapper("sv1")


def main() -> None:
    report = {}
    for name, edited in CASES.items():
        mapper = new_mapper()
        mapper._diff_todos(BASE)
        before = {p.content: p.task_id for p in mapper.ctx.todos}
        events = mapper._diff_todos(edited)
        after = {p.content: p.task_id for p in mapper.ctx.todos}
        kept_wrong = [content for content, task_id in after.items() if content in before and before[content] != task_id]
        report[name] = {
            "unchanged_rows_that_lost_their_id": kept_wrong,
            "events": [
                type(e).__name__ + ":" + str(getattr(e, "name", "") or "") + ":" + str(getattr(e, "status", "") or "")
                for e in events
            ],
            "aligned": not kept_wrong,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
