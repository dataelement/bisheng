"""Immutable, bounded JSONL batch approvals; execution truth stays in SQL audit."""

import json
import os
from pathlib import Path

from bisheng.permission.application.department_batch_repair import BATCH_FORMAT, validate_plan
from bisheng.permission.domain.services.department_recovery_plan import RecoveryBlockedError
from scripts.f048_department_recovery_io import create_file, encoded

MAX_BYTES = 512 * 1024 * 1024
MAX_LINE = 1024 * 1024 + 65536


def write_batch_plan(path, plan):
    validate_plan(plan)
    total = 0
    with create_file(path) as stream:
        header = {
            key: value
            for key, value in plan.items()
            if key not in {"entries", "plan_checksum", "complete", "all_repairable"}
        }
        records = [{"event": "plan_header", **header}]
        records.extend({"event": "plan_item", "entry": entry} for entry in plan["entries"])
        records.append(
            {
                "event": "plan_footer",
                "complete": plan["complete"],
                "all_repairable": plan["all_repairable"],
                "item_count": len(plan["entries"]),
                "plan_checksum": plan["plan_checksum"],
            }
        )
        for record in records:
            data = encoded(record)
            total += len(data)
            if len(data) > MAX_LINE or total > MAX_BYTES:
                raise RecoveryBlockedError("BATCH_PLAN_EVIDENCE_TOO_LARGE_INCOMPLETE")
            stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def read_batch_plan(path, expected_checksum=None):
    total, header, footer, entries = 0, None, None, []
    with open(path, "rb") as stream:
        while raw := stream.readline(MAX_LINE + 1):
            total += len(raw)
            if total > MAX_BYTES or len(raw) > MAX_LINE:
                raise RecoveryBlockedError("BATCH_PLAN_SIZE_INVALID")
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise RecoveryBlockedError("BATCH_PLAN_JSON_INVALID") from exc
            if not isinstance(value, dict) or footer is not None:
                raise RecoveryBlockedError("BATCH_PLAN_ORDER_INVALID")
            event = value.get("event")
            if header is None:
                if event != "plan_header" or value.get("format") != BATCH_FORMAT:
                    raise RecoveryBlockedError("BATCH_PLAN_VERSION_INVALID")
                header = {key: item for key, item in value.items() if key != "event"}
            elif event == "plan_item":
                if not isinstance(value.get("entry"), dict):
                    raise RecoveryBlockedError("BATCH_PLAN_ENTRY_INVALID")
                entries.append(value["entry"])
            elif event == "plan_footer":
                footer = value
            else:
                raise RecoveryBlockedError("BATCH_PLAN_EVENT_INVALID")
    if header is None or footer is None or footer.get("item_count") != len(entries):
        raise RecoveryBlockedError("BATCH_PLAN_INCOMPLETE")
    plan = header | {
        "entries": entries,
        "complete": footer.get("complete"),
        "all_repairable": footer.get("all_repairable"),
        "plan_checksum": footer.get("plan_checksum"),
    }
    validate_plan(plan)
    if expected_checksum is not None and plan["plan_checksum"] != expected_checksum:
        raise RecoveryBlockedError("BATCH_CONFIRMATION_CHECKSUM_MISMATCH")
    return plan


def private_batch_plan(source, directory, checksum):
    destination = Path(directory) / "confirmed-plan.jsonl"
    total = 0
    with open(source, "rb") as original, create_file(destination) as target:
        while chunk := original.read(65536):
            total += len(chunk)
            if total > MAX_BYTES:
                raise RecoveryBlockedError("BATCH_PLAN_SIZE_INVALID")
            target.write(chunk)
        target.flush()
        os.fsync(target.fileno())
    destination.chmod(0o400)
    return read_batch_plan(destination, checksum)
