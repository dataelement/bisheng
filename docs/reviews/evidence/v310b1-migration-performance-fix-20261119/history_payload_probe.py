"""Run from src/backend with this checkout on PYTHONPATH; offline configuration only.

Baseline: python <probe> --rows 1000
Fixed:    python <probe> --rows 1000 --disk
Repeat with 2000 rows in a fresh process. RSS includes imports and fixture creation;
Python allocation/timing starts after the input has been assembled. No service IO.
"""

import argparse
import json
import resource
import socket
import sys
import time
import tracemalloc
from contextlib import ExitStack


def deny_network(*args, **kwargs):
    raise RuntimeError("offline history payload probe must not connect to a service")


socket.socket.connect = deny_network
socket.create_connection = deny_network

from scripts import f118_history_business as business  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--rows", type=int, required=True)
parser.add_argument("--disk", action="store_true")
args = parser.parse_args()
with ExitStack() as scope:
    data = {"knowledge": [], "knowledgefile": [], "knowledge_document": []}
    if args.disk:
        from scripts.f118_history_snapshot import SnapshotStore

        store = scope.enter_context(SnapshotStore())
        for start in range(0, args.rows, 25):
            store.append(
                "knowledge",
                [
                    {"id": i, "payload": str(i) + "x" * 65536}
                    for i in range(start, min(start + 25, args.rows))
                ],
            )
        data["knowledge"] = store.rows("knowledge")
    else:
        data["knowledge"] = [
            {"id": i, "payload": str(i) + "x" * 65536} for i in range(args.rows)
        ]
    started = time.perf_counter()
    tracemalloc.start()
    digest = business.state_digest(data)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        json.dumps(
            {
                "rows": args.rows,
                "row_payload_bytes": 65536,
                "disk": args.disk,
                "digest": digest,
                "digest_python_peak_bytes": peak,
                "process_peak_rss_bytes": resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss
                * (1 if sys.platform == "darwin" else 1024),
                "digest_seconds": round(time.perf_counter() - started, 4),
            }
        )
    )
