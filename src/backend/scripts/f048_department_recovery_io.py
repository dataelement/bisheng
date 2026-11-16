"""Operator-owned evidence files; none of these files is a commit oracle."""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

FORMAT = "f078.department-recovery.v1"


def encoded(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def create_file(path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb")


class RecoveryAudit:
    def __init__(self, directory):
        self.path = Path(directory)
        self.path.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.run_id = uuid4().hex
        self.context = {}
        self.scan = create_file(self.path / "scan.jsonl")
        self.results = create_file(self.path / "results.jsonl")

    def emit(self, event, **fields):
        record = {"event": event, "run_id": self.run_id, **self.context, **fields}
        target = self.scan if event.startswith("scan") or event == "item_inspected" else self.results
        target.write(encoded(record))
        target.flush()
        os.fsync(target.fileno())

    async def before(self, payload):
        def save():
            name = f"before-{payload['tenant_id']}-{payload['department_id']}-{payload['operation']['id']}.json"
            with create_file(self.path / name) as stream:
                stream.write(encoded({"run_id": self.run_id, "preview": payload}))
                stream.flush()
                os.fsync(stream.fileno())

        await asyncio.to_thread(save)
        self.emit("before_saved", department_id=payload["department_id"], operation_id=payload["operation"]["id"])

    def close(self):
        self.scan.close()
        self.results.close()
