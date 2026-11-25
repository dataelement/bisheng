"""Closed F118 result/after directories; receipt bytes alone never authorize writes."""

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.knowledge.application.unification_inventory_codec import record_from_row
from bisheng.knowledge.domain.repositories.unification_conversion_repository import KINDS, ConversionOutcome
from bisheng.knowledge.domain.schemas.unification_conversion import DefaultConversionCommand, DefaultSlotProvenance
from bisheng.knowledge.domain.services.unification_conversion import (
    SQLConversionProgress,
    UnificationConversionService,
    _progress,
)
from bisheng.knowledge.domain.services.unification_fingerprints import canonical, digest

PHASES = ("converting", "backfilling", "verifying", "verified", "completed")


def blocked(reason):
    raise ReferenceCoverageNotReadyError(reason="migration_stage_receipt_" + reason)


def identity(frozen, tenant=None):
    value = {
        "run_id": frozen.run_id,
        "writer_contract_version": frozen.writer_contract_version,
        "baseline_hash": frozen.baseline_ref["sha256"],
        "plan_hash": frozen.plan_ref["sha256"],
    }
    if tenant is not None:
        value["tenant_id"] = tenant
    return value


def checkpoint(payload, count):
    return {
        "cursor": canonical(payload).decode(),
        "processed_count": count,
        "digest": digest(payload),
        "complete": True,
    }


def payload(value):
    try:
        result = json.loads(value["cursor"])
        if (
            set(value) != {"cursor", "processed_count", "digest", "complete"}
            or canonical(result).decode() != value["cursor"]
            or digest(result) != value["digest"]
        ):
            blocked("checkpoint_changed")
        return result
    except (KeyError, ValueError, TypeError) as error:
        raise ReferenceCoverageNotReadyError(reason="migration_stage_receipt_checkpoint_invalid") from error


def find(run, key):
    found = [run.checkpoints.get(phase, {}).get(key) for phase in PHASES]
    values = [value for value in found if value is not None]
    if values and any(value != values[0] for value in values):
        blocked("conflicting_stage_receipts")
    return values[0] if values else None


async def put_record(store, frozen, record):
    return await store.aput_canonical(
        run_id=frozen.run_id,
        kind="verification",
        content=canonical({"schema_version": 1, "run_id": frozen.run_id, "kind": "verification", "records": [record]}),
    )


async def load_record(store, frozen, ref):
    value = json.loads(await store.aload_canonical(ref, run_id=frozen.run_id, kind="verification"))
    if len(value["records"]) != 1 or type(value["records"][0]) is not dict:
        blocked("record_envelope")
    return value["records"][0]


async def put_directory(store, frozen, *, purpose, records, batch_size=2000):
    refs, page, size, total = [], [], 0, 0
    for record in records:
        encoded = canonical(record)
        if len(encoded) > 8 * 1024 * 1024:
            blocked("directory_record_too_large")
        if page and (len(page) >= batch_size or size + len(encoded) > 8 * 1024 * 1024):
            refs.append(
                await store.aput_canonical(
                    run_id=frozen.run_id,
                    kind="verification",
                    content=canonical(
                        {"schema_version": 1, "run_id": frozen.run_id, "kind": "verification", "records": page}
                    ),
                )
            )
            page, size = [], 0
        page.append(record)
        total += 1
        size += len(encoded)
    if page:
        refs.append(
            await store.aput_canonical(
                run_id=frozen.run_id,
                kind="verification",
                content=canonical(
                    {"schema_version": 1, "run_id": frozen.run_id, "kind": "verification", "records": page}
                ),
            )
        )
    return await put_record(
        store,
        frozen,
        {"schema_version": 1, "purpose": purpose, "identity": identity(frozen), "pages": refs, "count": total},
    )


async def iter_directory(store, frozen, ref, *, purpose):
    root = await load_record(store, frozen, ref)
    if (
        set(root) != {"schema_version", "purpose", "identity", "pages", "count"}
        or root["schema_version"] != 1
        or root["purpose"] != purpose
        or root["identity"] != identity(frozen)
        or type(root["pages"]) is not list
        or type(root["count"]) is not int
    ):
        blocked("directory_binding")
    count, seen = 0, set()
    for page in root["pages"]:
        if page["sha256"] in seen:
            blocked("duplicate_directory_page")
        seen.add(page["sha256"])
        body = json.loads(await store.aload_canonical(page, run_id=frozen.run_id, kind="verification"))
        for record in body["records"]:
            count += 1
            yield record
    if count != root["count"]:
        blocked("directory_count")


def restore_commands(rows):
    commands, classes = [], {value: cls for cls, value in KINDS.items()}
    for values in rows:
        data = dict(values)
        try:
            cls = classes[data["operation"]]
            for name in ("planned_at", "creator_planned_at"):
                if name in data and data[name] is not None:
                    data[name] = datetime.fromisoformat(data[name])
            if cls is DefaultConversionCommand:
                data["provenance"] = tuple(DefaultSlotProvenance(**row) for row in data["provenance"])
            command = cls(**data)
            record_from_row(command)
            if canonical(asdict(command)) != canonical(values):
                blocked("command_roundtrip")
            commands.append(command)
        except (KeyError, TypeError, ValueError) as error:
            raise ReferenceCoverageNotReadyError(reason="migration_stage_receipt_command_invalid") from error
    return tuple(commands)


def result_body(tail, frozen, tenant):
    body = payload(tail)
    expected = {
        "schema_version",
        "purpose",
        "identity",
        "sequence",
        "start",
        "previous_progress",
        "sql_checkpoint",
        "directory",
        "predecessor",
        "commands",
        "outcomes",
        "outcome_digest",
    }
    if (
        set(body) != expected
        or body["schema_version"] != 1
        or body["purpose"] != "sql-results-v1"
        or body["identity"] != identity(frozen, tenant)
    ):
        blocked("result_binding")
    progress = _progress(body["sql_checkpoint"])
    if (
        tail["processed_count"] != progress.processed_count
        or tail["complete"] != progress.complete
        or type(body["sequence"]) is not int
        or body["sequence"] < 0
        or type(body["start"]) is not int
        or body["start"] < 0
        or type(body["commands"]) is not list
        or len(body["commands"]) > 200
    ):
        blocked("result_position")
    commands = restore_commands(body["commands"])
    try:
        outcomes = tuple(ConversionOutcome(**row) for row in body["outcomes"])
        previous = SQLConversionProgress(**body["previous_progress"])
    except (TypeError, ValueError) as error:
        raise ReferenceCoverageNotReadyError(reason="migration_stage_receipt_outcomes_invalid") from error
    if previous.processed_count != body["start"] or digest(body["outcomes"]) != body["outcome_digest"]:
        blocked("result_outcome_digest")
    actual = UnificationConversionService()._fold(
        SimpleNamespace(commands=commands), previous, outcomes, complete=progress.complete
    )
    if actual != progress:
        blocked("result_fold_changed")
    if body["sequence"] == 0:
        seed = digest({"sql_conversion": 1, **identity(frozen, tenant)})
        if (
            body["start"] != 0
            or body["predecessor"] is not None
            or previous != SQLConversionProgress(None, 0, seed, False)
        ):
            blocked("result_seed")
    elif body["predecessor"] is None:
        blocked("result_predecessor_missing")
    return body, commands, outcomes


async def iter_results(store, frozen, tenant, head):
    """Check the complete linked directory before yielding forward batches."""
    with TemporaryDirectory(prefix="f118-sql-result-chain-") as directory:
        path = Path(directory) / "chain.sqlite"
        path.touch(mode=0o600)
        database = sqlite3.connect(path)
        try:
            database.execute("CREATE TABLE pages(sequence INTEGER PRIMARY KEY, hash TEXT UNIQUE, payload TEXT)")
            ref, next_body = head, None
            while ref is not None:
                body = await load_record(store, frozen, ref)
                tail = {
                    "cursor": canonical(body).decode(),
                    "processed_count": body["sql_checkpoint"]["processed_count"],
                    "digest": digest(body),
                    "complete": body["sql_checkpoint"]["complete"],
                }
                body, _, _ = result_body(tail, frozen, tenant)
                if next_body is not None and (
                    body["sequence"] + 1 != next_body["sequence"]
                    or body["sql_checkpoint"] != next_body["previous_progress"]
                    or body["directory"] != next_body["directory"]
                ):
                    blocked("result_chain_changed")
                try:
                    database.execute(
                        "INSERT INTO pages VALUES (?,?,?)", (body["sequence"], ref["sha256"], canonical(body).decode())
                    )
                except sqlite3.IntegrityError as error:
                    raise ReferenceCoverageNotReadyError(reason="migration_stage_receipt_result_cycle") from error
                next_body, ref = body, body["predecessor"]
            if next_body is None or next_body["sequence"] != 0:
                blocked("result_chain_incomplete")
            for (encoded,) in database.execute("SELECT payload FROM pages ORDER BY sequence"):
                body = json.loads(encoded)
                tail = {
                    "cursor": encoded,
                    "processed_count": body["sql_checkpoint"]["processed_count"],
                    "digest": digest(body),
                    "complete": body["sql_checkpoint"]["complete"],
                }
                yield result_body(tail, frozen, tenant)
        finally:
            database.close()
