#!/usr/bin/env python3
"""Backfill message-to-citation relations after the shared-citation hotfix.

``message_citation`` historically stored both the citation payload and its first
``message_id``. The hotfix keeps that global payload row and adds
``message_citation_relation`` so the same citation can be associated with more
than one output message.

Run from ``src/backend/`` after the upgraded service has created the relation
table. Dry-run is the default; add ``--apply`` to write. ``--recover-markers``
also scans message text for citation markers and can repair previously committed
messages whose citation write failed on the old global unique index.

    config=config.yaml PYTHONPATH=./ .venv/bin/python \
        scripts/backfill_message_citation_relations.py
    config=config.yaml PYTHONPATH=./ .venv/bin/python \
        scripts/backfill_message_citation_relations.py --recover-markers --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import col, select  # noqa: E402

from bisheng.citation.domain.models.message_citation import (  # noqa: E402
    MessageCitation,
    MessageCitationRelation,
)
from bisheng.citation.domain.repositories.implementations.message_citation_repository_impl import (  # noqa: E402
    MessageCitationRepositoryImpl,
)
from bisheng.citation.domain.services.citation_prompt_helper import (  # noqa: E402
    CITATION_START_MARKER,
    extract_citation_ids_from_text,
)
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.models.message import ChatMessage  # noqa: E402

DEFAULT_BATCH_SIZE = 500


@dataclass
class BackfillReport:
    legacy_candidates: int = 0
    marker_messages: int = 0
    marker_references: int = 0
    created: int = 0
    skipped_existing: int = 0
    skipped_missing_citation: int = 0
    skipped_scope_mismatch: int = 0


def _chunks(values: list[str], batch_size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), batch_size):
        yield values[index : index + batch_size]


async def _load_existing_relation_keys(
    session,
    relations: list[MessageCitationRelation],
) -> set[tuple[int, str]]:
    if not relations:
        return set()

    relation_keys = {(relation.message_id, relation.citation_id) for relation in relations}
    message_ids = list({message_id for message_id, _ in relation_keys})
    citation_ids = list({citation_id for _, citation_id in relation_keys})
    result = await session.exec(
        select(MessageCitationRelation).where(
            col(MessageCitationRelation.message_id).in_(message_ids),
            col(MessageCitationRelation.citation_id).in_(citation_ids),
        )
    )
    return {
        (relation.message_id, relation.citation_id)
        for relation in result.all()
        if (relation.message_id, relation.citation_id) in relation_keys
    }


async def _persist_candidates(
    session,
    relations: list[MessageCitationRelation],
    report: BackfillReport,
    *,
    apply: bool,
) -> None:
    desired = {(relation.message_id, relation.citation_id): relation for relation in relations}
    existing_keys = await _load_existing_relation_keys(session, list(desired.values()))
    report.skipped_existing += len(existing_keys)
    missing = [relation for relation_key, relation in desired.items() if relation_key not in existing_keys]
    report.created += len(missing)
    if apply and missing:
        repository = MessageCitationRepositoryImpl(session)
        await repository.ensure_relations(missing)


async def _backfill_legacy_owners(
    session,
    report: BackfillReport,
    *,
    apply: bool,
    batch_size: int,
) -> None:
    last_citation_pk = 0
    while True:
        result = await session.exec(
            select(
                MessageCitation.id,
                MessageCitation.message_id,
                MessageCitation.citation_id,
                ChatMessage.tenant_id,
            )
            .outerjoin(ChatMessage, ChatMessage.id == MessageCitation.message_id)
            .where(MessageCitation.id > last_citation_pk)
            .order_by(MessageCitation.id.asc())
            .limit(batch_size)
        )
        rows = list(result.all())
        if not rows:
            return

        last_citation_pk = rows[-1][0]
        relations = [
            MessageCitationRelation(
                tenant_id=tenant_id or 1,
                message_id=message_id,
                citation_id=citation_id,
            )
            for _, message_id, citation_id, tenant_id in rows
        ]
        report.legacy_candidates += len(relations)
        await _persist_candidates(session, relations, report, apply=apply)


async def _load_citations_by_id(
    session,
    citation_ids: set[str],
    *,
    batch_size: int,
) -> dict[str, MessageCitation]:
    citations: dict[str, MessageCitation] = {}
    ordered_ids = list(citation_ids)
    for citation_id_batch in _chunks(ordered_ids, batch_size):
        result = await session.exec(
            select(MessageCitation).where(col(MessageCitation.citation_id).in_(citation_id_batch))
        )
        citations.update({citation.citation_id: citation for citation in result.all()})
    return citations


def _citation_matches_message_scope(
    citation: MessageCitation,
    *,
    chat_id: str | None,
    flow_id: str,
) -> bool:
    if citation.chat_id is not None and citation.chat_id != chat_id:
        return False
    return citation.flow_id is None or citation.flow_id == flow_id


async def _recover_marker_relations(
    session,
    report: BackfillReport,
    *,
    apply: bool,
    batch_size: int,
) -> None:
    last_message_id = 0
    while True:
        result = await session.exec(
            select(
                ChatMessage.id,
                ChatMessage.tenant_id,
                ChatMessage.chat_id,
                ChatMessage.flow_id,
                ChatMessage.message,
            )
            .where(
                ChatMessage.id > last_message_id,
                ChatMessage.message.contains(CITATION_START_MARKER),
            )
            .order_by(ChatMessage.id.asc())
            .limit(batch_size)
        )
        rows = list(result.all())
        if not rows:
            return

        last_message_id = rows[-1][0]
        report.marker_messages += len(rows)
        citation_ids_by_message = {
            message_id: extract_citation_ids_from_text(message or "") for message_id, _, _, _, message in rows
        }
        all_citation_ids = {
            citation_id for citation_ids in citation_ids_by_message.values() for citation_id in citation_ids
        }
        citation_map = await _load_citations_by_id(
            session,
            all_citation_ids,
            batch_size=batch_size,
        )

        relations: list[MessageCitationRelation] = []
        for message_id, tenant_id, chat_id, flow_id, _ in rows:
            citation_ids = citation_ids_by_message[message_id]
            report.marker_references += len(citation_ids)
            for citation_id in citation_ids:
                citation = citation_map.get(citation_id)
                if citation is None:
                    report.skipped_missing_citation += 1
                    continue
                if citation.message_id == message_id:
                    continue
                if not _citation_matches_message_scope(
                    citation,
                    chat_id=chat_id,
                    flow_id=flow_id,
                ):
                    report.skipped_scope_mismatch += 1
                    continue
                relations.append(
                    MessageCitationRelation(
                        tenant_id=tenant_id or 1,
                        message_id=message_id,
                        citation_id=citation_id,
                    )
                )
        await _persist_candidates(session, relations, report, apply=apply)


async def backfill(
    session,
    *,
    apply: bool,
    recover_markers: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> BackfillReport:
    """Backfill direct legacy ownership and optionally recover marker relations."""
    report = BackfillReport()
    await _backfill_legacy_owners(
        session,
        report,
        apply=apply,
        batch_size=batch_size,
    )
    if recover_markers:
        await _recover_marker_relations(
            session,
            report,
            apply=apply,
            batch_size=batch_size,
        )
    return report


async def _run(args) -> int:
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            report = await backfill(
                session,
                apply=args.apply,
                recover_markers=args.recover_markers,
                batch_size=args.batch_size,
            )

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(
        f"[{mode}] legacy_candidates={report.legacy_candidates} "
        f"marker_messages={report.marker_messages} "
        f"marker_references={report.marker_references} "
        f"{'created' if args.apply else 'would_create'}={report.created} "
        f"skipped_existing={report.skipped_existing} "
        f"skipped_missing_citation={report.skipped_missing_citation} "
        f"skipped_scope_mismatch={report.skipped_scope_mismatch}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument(
        "--recover-markers",
        action="store_true",
        help="also scan persisted messages for reusable citation markers",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"rows per batch (default: {DEFAULT_BATCH_SIZE})",
    )
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than zero")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
