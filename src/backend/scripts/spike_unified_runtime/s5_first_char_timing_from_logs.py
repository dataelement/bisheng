"""S5: where does the time go before the first answer character in daily chat?

Reads an extract of the backend log (not the live service) and, per request
trace, measures:
  * prep  = request received -> first model request sent
  * ttft  = the model's own time to first token (already logged as BS_METRIC)
split by whether the request carried tools and attachments.

It needs no login and changes nothing on the server. Build the extract on the
host that owns the log (two read-only greps), then run this script anywhere:

    grep -F "/api/v1/workstation/chat/completions" bisheng.log | grep -F "| POST " \\
        | grep -v HTTP_ACCESS_METRIC | grep -o "trace=[0-9a-f]*" | sort -u > traces.txt
    grep -F -f traces.txt bisheng.log | grep -E "\\| POST http|build_user_content\\] scenario|\\
loaded [0-9]+ chat history|prepared messages|url.: ./chat/completions|domain=model_invoke|\\
process_agent_files\\]|TASK_TITLE|linsight" > extract.log

    python scripts/spike_unified_runtime/s5_first_char_timing_from_logs.py extract.log
"""

from __future__ import annotations

import collections
import datetime
import re
import statistics
import sys

LINE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\] \[\w+ [^\]]*? [\w.]+:\d+\] - trace=(\w+) (.*)")


def quantiles(values: list[float]) -> str:
    values = sorted(values)
    n = len(values)
    p90 = values[max(0, int(n * 0.9) - 1)]
    return f"n={n} p50={statistics.median(values):.2f} p90={p90:.2f} min={values[0]:.2f} max={values[-1]:.2f}"


def main(path: str) -> int:
    by_trace: dict[str, list[tuple[datetime.datetime, str]]] = collections.defaultdict(list)
    with open(path, errors="replace") as handle:
        for line in handle:
            match = LINE.match(line)
            if match:
                stamp = datetime.datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S.%f")
                by_trace[match[2]].append((stamp, match[3]))

    rows = []
    for events in by_trace.values():
        events.sort()

        def first(pred, events=events):
            return next(((t, m) for t, m in events if pred(m)), (None, None))

        start, _ = first(lambda m: "| POST http" in m and "HTTP_ACCESS" not in m)
        sent, _ = first(lambda m: "'/chat/completions'" in m)
        _, metric = first(lambda m: "domain=model_invoke" in m and "is_stream=1" in m)
        if not start or not sent or not metric:
            continue
        if any("TASK_TITLE" in m or "linsight" in m.lower() for _, m in events):
            continue  # deep-research turn: the model call here is title generation
        _, prepared = first(lambda m: "prepared messages" in m)
        rows.append(
            {
                "prep": (sent - start).total_seconds(),
                "ttft": float(re.search(r"ttft_ms=([\d.]+)", metric)[1]) / 1000,
                "tools": int(re.search(r"tool_count=(\d+)", prepared)[1]) if prepared else 0,
                "files": any("process_agent_files] docs" in m for _, m in events),
            }
        )

    groups = {
        "no attachments": [r for r in rows if not r["files"]],
        "with attachments": [r for r in rows if r["files"]],
    }
    print(f"daily-chat requests with a model call: {len(rows)}")
    for name, group in groups.items():
        if not group:
            print(f"-- {name}: n=0")
            continue
        print(f"-- {name}")
        print("   prep, s:                ", quantiles([r["prep"] for r in group]))
        print("   model ttft, s:          ", quantiles([r["ttft"] for r in group]))
        print("   first char (sum), s:    ", quantiles([r["prep"] + r["ttft"] for r in group]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
