"""Audit and recover orphaned F068 knowledge-chat entry locations.

The script is DB-only. It classifies every knowledge-space session in the
selected session tenant scope and, in ``--apply`` mode, points active orphaned
sessions at their original space root without changing the content ``flow_id``.

Run from ``src/backend`` with the same ``config`` as the live service. Dry-run
is the default. Apply requires the SHA-256 printed by a preceding dry-run::

    python scripts/migrate_f068_knowledge_chat_entries.py --tenant-id 3
    python scripts/migrate_f068_knowledge_chat_entries.py --tenant-id 3 \
      --apply --expected-input-sha256 <sha256>
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.engine import make_url
from sqlmodel import col, select, update

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.models.flow import FlowType  # noqa: E402
from bisheng.database.models.session import MessageSession  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import Knowledge  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_file import (  # noqa: E402
    FileType,
    KnowledgeFile,
)

EXIT_BLOCKED = 2
EXIT_CONFIRMATION_MISMATCH = 3
EXIT_VALIDATION_FAILED = 4

FLOW_RE = re.compile(r"^space_(?P<space_id>[1-9]\d*)_(?P<kind>folder|file)_(?P<resource_id>\d+)$")
RECOVERABLE_CATEGORIES = frozenset({"recoverable_missing", "recoverable_moved"})
BLOCKER_CATEGORIES = frozenset({"unparseable", "cross_tenant_conflict", "resource_type_conflict"})


@dataclass(frozen=True)
class ParsedFlow:
    space_id: int
    kind: str
    resource_id: int

    @property
    def root_flow_id(self) -> str:
        return f"space_{self.space_id}_folder_0"


@dataclass(frozen=True)
class SessionSnapshot:
    tenant_id: int
    chat_id: str
    flow_id: str
    flow_type: int
    is_delete: bool
    entry_flow_id: str | None


@dataclass(frozen=True)
class SpaceSnapshot:
    space_id: int
    tenant_id: int


@dataclass(frozen=True)
class ResourceSnapshot:
    resource_id: int
    knowledge_id: int
    tenant_id: int
    file_type: int


@dataclass(frozen=True)
class ManifestItem:
    tenant_id: int
    chat_id: str
    flow_id: str
    flow_type: int
    is_delete: bool
    category: str
    source_space_id: int | None
    resource_kind: str | None
    resource_id: int | None
    current_space_id: int | None
    current_resource_tenant_id: int | None
    current_space_tenant_id: int | None

    def immutable_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScanResult:
    sessions: tuple[SessionSnapshot, ...]
    manifest: tuple[ManifestItem, ...]
    manifest_sha256: str
    invalid_non_knowledge_entry_count: int
    invalid_entry_grammar_count: int
    cross_space_entry_count: int

    @property
    def category_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(item.category for item in self.manifest).items()))

    @property
    def blocker_count(self) -> int:
        return sum(self.category_counts.get(category, 0) for category in BLOCKER_CATEGORIES)

    @property
    def recoverable_orphan_remaining(self) -> int:
        entries = {session.chat_id: session.entry_flow_id for session in self.sessions}
        return sum(
            item.category in RECOVERABLE_CATEGORIES and entries.get(item.chat_id) is None for item in self.manifest
        )

    @property
    def invalid_entry_count(self) -> int:
        return self.invalid_non_knowledge_entry_count + self.invalid_entry_grammar_count + self.cross_space_entry_count


def parse_flow_id(flow_id: str) -> ParsedFlow | None:
    match = FLOW_RE.fullmatch(flow_id or "")
    if not match:
        return None
    parsed = ParsedFlow(
        space_id=int(match.group("space_id")),
        kind=match.group("kind"),
        resource_id=int(match.group("resource_id")),
    )
    if parsed.kind == "file" and parsed.resource_id == 0:
        return None
    return parsed


def classify_session(
    session: SessionSnapshot,
    spaces: dict[int, SpaceSnapshot],
    resources: dict[int, ResourceSnapshot],
) -> ManifestItem:
    parsed = parse_flow_id(session.flow_id)
    if session.is_delete:
        category = "soft_deleted"
    elif parsed is None:
        category = "unparseable"
    elif parsed.space_id not in spaces:
        category = "deleted_space_skipped"
    elif parsed.kind == "folder" and parsed.resource_id == 0:
        category = "native_root"
    else:
        resource = resources.get(parsed.resource_id)
        if resource is None:
            category = "recoverable_missing"
        else:
            expected_file_type = FileType.DIR.value if parsed.kind == "folder" else FileType.FILE.value
            source_space = spaces[parsed.space_id]
            current_space = spaces.get(resource.knowledge_id)
            if resource.file_type != expected_file_type:
                category = "resource_type_conflict"
            elif resource.tenant_id != source_space.tenant_id or (
                current_space is not None and current_space.tenant_id != source_space.tenant_id
            ):
                category = "cross_tenant_conflict"
            elif resource.knowledge_id == parsed.space_id:
                category = "resource_present"
            else:
                category = "recoverable_moved"

    resource = resources.get(parsed.resource_id) if parsed and parsed.resource_id else None
    current_space = spaces.get(resource.knowledge_id) if resource else None
    return ManifestItem(
        tenant_id=session.tenant_id,
        chat_id=session.chat_id,
        flow_id=session.flow_id,
        flow_type=session.flow_type,
        is_delete=session.is_delete,
        category=category,
        source_space_id=parsed.space_id if parsed else None,
        resource_kind=parsed.kind if parsed else None,
        resource_id=parsed.resource_id if parsed else None,
        current_space_id=resource.knowledge_id if resource else None,
        current_resource_tenant_id=resource.tenant_id if resource else None,
        current_space_tenant_id=current_space.tenant_id if current_space else None,
    )


def build_manifest(
    sessions: Sequence[SessionSnapshot],
    spaces: dict[int, SpaceSnapshot],
    resources: dict[int, ResourceSnapshot],
) -> tuple[ManifestItem, ...]:
    return tuple(
        sorted(
            (classify_session(session, spaces, resources) for session in sessions),
            key=lambda item: (item.tenant_id, item.chat_id),
        )
    )


def manifest_sha256(manifest: Sequence[ManifestItem]) -> str:
    payload = [item.immutable_payload() for item in manifest]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def mask_chat_id(chat_id: str) -> str:
    if len(chat_id) <= 6:
        return "*" * len(chat_id)
    return f"{chat_id[:3]}...{chat_id[-3:]}"


def database_identity(database_url: str) -> dict[str, Any]:
    url = make_url(database_url)
    return {
        "driver": url.drivername,
        "host": url.host,
        "port": url.port,
        "database": url.database,
        "username": url.username,
    }


def _chunks(values: Sequence[int], size: int) -> Iterable[Sequence[int]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


async def _load_spaces(session, space_ids: set[int], batch_size: int) -> dict[int, SpaceSnapshot]:
    spaces: dict[int, SpaceSnapshot] = {}
    for ids in _chunks(sorted(space_ids), batch_size):
        rows = (await session.exec(select(Knowledge).where(col(Knowledge.id).in_(ids)))).all()
        spaces.update(
            {
                int(row.id): SpaceSnapshot(space_id=int(row.id), tenant_id=int(row.tenant_id))
                for row in rows
                if row.id is not None and row.tenant_id is not None
            }
        )
    return spaces


async def _load_resources(
    session,
    resource_ids: set[int],
    batch_size: int,
) -> dict[int, ResourceSnapshot]:
    resources: dict[int, ResourceSnapshot] = {}
    for ids in _chunks(sorted(resource_ids), batch_size):
        rows = (await session.exec(select(KnowledgeFile).where(col(KnowledgeFile.id).in_(ids)))).all()
        resources.update(
            {
                int(row.id): ResourceSnapshot(
                    resource_id=int(row.id),
                    knowledge_id=int(row.knowledge_id),
                    tenant_id=int(row.tenant_id),
                    file_type=int(row.file_type),
                )
                for row in rows
                if row.id is not None and row.tenant_id is not None
            }
        )
    return resources


def validate_entry(session: SessionSnapshot) -> tuple[int, int]:
    if session.entry_flow_id is None:
        return 0, 0
    source = parse_flow_id(session.flow_id)
    entry = parse_flow_id(session.entry_flow_id)
    if source is None or entry is None or entry.kind != "folder" or entry.resource_id != 0:
        return 1, 0
    if source.space_id != entry.space_id:
        return 0, 1
    return 0, 0


async def scan_database(tenant_id: int | None, batch_size: int) -> ScanResult:
    with bypass_tenant_filter():
        async with get_async_db_session() as db:
            statement = select(MessageSession).where(MessageSession.flow_type == FlowType.KNOLEDGE_SPACE.value)
            if tenant_id is not None:
                statement = statement.where(MessageSession.tenant_id == tenant_id)
            rows = (await db.exec(statement)).all()
            sessions = tuple(
                SessionSnapshot(
                    tenant_id=int(row.tenant_id),
                    chat_id=row.chat_id,
                    flow_id=row.flow_id,
                    flow_type=int(row.flow_type),
                    is_delete=bool(row.is_delete),
                    entry_flow_id=row.entry_flow_id,
                )
                for row in rows
                if row.tenant_id is not None
            )

            parsed = [parse_flow_id(item.flow_id) for item in sessions]
            source_space_ids = {item.space_id for item in parsed if item is not None}
            resource_ids = {item.resource_id for item in parsed if item is not None and item.resource_id > 0}
            resources = await _load_resources(db, resource_ids, batch_size)
            all_space_ids = source_space_ids | {item.knowledge_id for item in resources.values()}
            spaces = await _load_spaces(db, all_space_ids, batch_size)

            non_knowledge_statement = select(MessageSession.chat_id).where(
                MessageSession.entry_flow_id.is_not(None),
                MessageSession.flow_type != FlowType.KNOLEDGE_SPACE.value,
            )
            if tenant_id is not None:
                non_knowledge_statement = non_knowledge_statement.where(MessageSession.tenant_id == tenant_id)
            invalid_non_knowledge = len((await db.exec(non_knowledge_statement)).all())

    manifest = build_manifest(sessions, spaces, resources)
    entry_results = [validate_entry(session) for session in sessions]
    return ScanResult(
        sessions=sessions,
        manifest=manifest,
        manifest_sha256=manifest_sha256(manifest),
        invalid_non_knowledge_entry_count=invalid_non_knowledge,
        invalid_entry_grammar_count=sum(result[0] for result in entry_results),
        cross_space_entry_count=sum(result[1] for result in entry_results),
    )


def load_checkpoint(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("checkpoint must contain a JSON object")
    return data


def save_checkpoint(path: Path, manifest_hash: str, cursor: tuple[int, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest_sha256": manifest_hash,
        "last_tenant_id": cursor[0],
        "last_chat_id": cursor[1],
    }
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _checkpoint_cursor(checkpoint: dict[str, Any] | None) -> tuple[int, str] | None:
    if checkpoint is None:
        return None
    return int(checkpoint["last_tenant_id"]), str(checkpoint["last_chat_id"])


def recoverable_items(scan: ScanResult, cursor: tuple[int, str] | None) -> list[ManifestItem]:
    session_by_chat = {session.chat_id: session for session in scan.sessions}
    items = []
    for item in scan.manifest:
        session = session_by_chat[item.chat_id]
        key = (item.tenant_id, item.chat_id)
        if (
            item.category in RECOVERABLE_CATEGORIES
            and not item.is_delete
            and session.entry_flow_id is None
            and (cursor is None or key > cursor)
        ):
            items.append(item)
    return items


async def apply_recovery(
    scan: ScanResult,
    batch_size: int,
    checkpoint_path: Path,
) -> int:
    checkpoint = load_checkpoint(checkpoint_path)
    if checkpoint and checkpoint.get("manifest_sha256") != scan.manifest_sha256:
        raise ValueError("checkpoint manifest SHA-256 does not match current input")
    cursor = _checkpoint_cursor(checkpoint)
    if cursor is not None and cursor not in {(item.tenant_id, item.chat_id) for item in scan.manifest}:
        raise ValueError("checkpoint cursor does not exist in the current manifest")
    pending = recoverable_items(scan, cursor)
    updated_total = 0

    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        groups: dict[str, list[ManifestItem]] = defaultdict(list)
        for item in batch:
            if item.source_space_id is None:
                raise ValueError("recoverable manifest item has no source space")
            groups[f"space_{item.source_space_id}_folder_0"].append(item)

        with bypass_tenant_filter():
            async with get_async_db_session() as db:
                for root_flow_id, items in groups.items():
                    row_fences = [
                        and_(
                            MessageSession.tenant_id == item.tenant_id,
                            MessageSession.chat_id == item.chat_id,
                            MessageSession.flow_id == item.flow_id,
                        )
                        for item in items
                    ]
                    statement = (
                        update(MessageSession)
                        .where(
                            or_(*row_fences),
                            MessageSession.flow_type == FlowType.KNOLEDGE_SPACE.value,
                            MessageSession.is_delete == False,  # noqa: E712
                            MessageSession.entry_flow_id.is_(None),
                        )
                        .values(entry_flow_id=root_flow_id)
                    )
                    result = await db.exec(statement)
                    rowcount = getattr(result, "rowcount", None)
                    updated_total += len(items) if rowcount is None or rowcount < 0 else int(rowcount)
                await db.commit()

        last = batch[-1]
        save_checkpoint(
            checkpoint_path,
            scan.manifest_sha256,
            (last.tenant_id, last.chat_id),
        )
    return updated_total


def report_for_scan(
    scan: ScanResult,
    *,
    mode: str,
    matched_count: int | None = None,
    updated_count: int = 0,
) -> dict[str, Any]:
    examples: dict[str, list[str]] = defaultdict(list)
    for item in scan.manifest:
        if len(examples[item.category]) < 5:
            examples[item.category].append(mask_chat_id(item.chat_id))
    return {
        "event": "knowledge_chat_entry.migration_summary",
        "mode": mode,
        "database": database_identity(settings.database_url),
        "manifest_sha256": scan.manifest_sha256,
        "session_count": len(scan.manifest),
        "category_counts": scan.category_counts,
        "category_chat_id_examples": dict(sorted(examples.items())),
        "blocker_count": scan.blocker_count,
        "invalid_non_knowledge_entry_count": scan.invalid_non_knowledge_entry_count,
        "invalid_entry_grammar_count": scan.invalid_entry_grammar_count,
        "cross_space_entry_count": scan.cross_space_entry_count,
        "recoverable_orphan_remaining": scan.recoverable_orphan_remaining,
        "matched_count": scan.recoverable_orphan_remaining if matched_count is None else matched_count,
        "updated_count": updated_count,
        "update_time_refreshed_count": updated_count,
        "deleted_space_skipped": scan.category_counts.get("deleted_space_skipped", 0),
    }


def _is_blocked(scan: ScanResult) -> bool:
    return scan.blocker_count > 0 or scan.invalid_entry_count > 0


async def run(args: argparse.Namespace) -> int:
    scan = await scan_database(args.tenant_id, args.batch_size)
    if not args.apply:
        print(json.dumps(report_for_scan(scan, mode="dry-run"), ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_BLOCKED if _is_blocked(scan) else 0

    if not args.expected_input_sha256:
        print("--apply requires --expected-input-sha256", file=sys.stderr)
        return EXIT_CONFIRMATION_MISMATCH
    if args.expected_input_sha256 != scan.manifest_sha256:
        print("expected input SHA-256 does not match current manifest", file=sys.stderr)
        return EXIT_CONFIRMATION_MISMATCH
    if _is_blocked(scan):
        print(json.dumps(report_for_scan(scan, mode="apply-blocked"), ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_BLOCKED

    matched_count = len(recoverable_items(scan, cursor=None))
    try:
        updated_count = await apply_recovery(scan, args.batch_size, args.checkpoint_file)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIRMATION_MISMATCH

    validation = await scan_database(args.tenant_id, args.batch_size)
    report = report_for_scan(
        validation,
        mode="apply",
        matched_count=matched_count,
        updated_count=updated_count,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if (
        validation.manifest_sha256 != scan.manifest_sha256
        or _is_blocked(validation)
        or validation.recoverable_orphan_remaining != 0
    ):
        return EXIT_VALIDATION_FAILED
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, help="Only scan sessions owned by this leaf tenant")
    parser.add_argument("--batch-size", type=int, default=500, help="Read/write batch size (default: 500)")
    parser.add_argument(
        "--checkpoint-file",
        type=Path,
        default=Path(".f068-knowledge-chat-entry.checkpoint.json"),
        help="Checkpoint JSON path",
    )
    parser.add_argument("--apply", action="store_true", help="Apply recoverable entry updates")
    parser.add_argument("--expected-input-sha256", help="Manifest SHA-256 from the reviewed dry-run")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    if args.tenant_id is not None and args.tenant_id <= 0:
        parser.error("--tenant-id must be positive")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
