"""Approval timestamps are written in local time, like every other column.

`create_time` / `update_time` come from the database clock (local), and the
publish face shows `instance.create_time` next to `task.acted_at` as
"submitted" / "decided". `acted_at` used to be written with
`datetime.utcnow()`, so on a UTC+8 server an approval read as decided eight
hours before it was submitted. Naive `DateTime` columns carry no zone, so
mixing the two is invisible until someone compares them.
"""

from pathlib import Path

# `bisheng.approval` is a namespace package (no __init__), so it has no __file__.
APPROVAL_ROOT = Path(__file__).resolve().parents[2] / "bisheng" / "approval"


def test_approval_module_never_writes_utc_naive_times():
    root = APPROVAL_ROOT
    assert root.is_dir()
    offenders = [
        f"{path.relative_to(root)}:{lineno}"
        for path in root.rglob("*.py")
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "utcnow(" in line
    ]
    assert offenders == [], f"use datetime.now() for naive DateTime columns: {offenders}"
