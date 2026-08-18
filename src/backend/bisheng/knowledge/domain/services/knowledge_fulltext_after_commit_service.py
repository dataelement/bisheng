"""Coordinate immediate fulltext Outbox publication after transaction commit."""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from sqlalchemy import event
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import (
    KnowledgeFulltextOutbox,
)

_PENDING_REFS_KEY = "knowledge_fulltext_after_commit_refs"
_LISTENERS_INSTALLED_KEY = "knowledge_fulltext_after_commit_listeners_installed"
_NESTED_SNAPSHOTS_KEY = "knowledge_fulltext_after_commit_nested_snapshots"
_ROLLED_BACK_NESTED_KEY = "knowledge_fulltext_after_commit_rolled_back_nested"


@dataclass(frozen=True)
class KnowledgeFulltextDispatchRef:
    outbox_id: int
    revision: int


def track_outbox_after_commit(
    session: Session | AsyncSession,
    row: KnowledgeFulltextOutbox,
) -> None:
    """Track the latest Outbox reference in the current transaction.

    Publication occurs only after the outermost transaction commits.
    """
    if row.id is None:
        raise ValueError("fulltext outbox must be flushed before after-commit tracking")
    sync_session = session.sync_session if isinstance(session, AsyncSession) else session
    _install_listeners(sync_session)
    _ensure_current_nested_snapshot(sync_session)
    refs: dict[int, KnowledgeFulltextDispatchRef] = sync_session.info.setdefault(
        _PENDING_REFS_KEY,
        {},
    )
    refs[int(row.id)] = KnowledgeFulltextDispatchRef(
        outbox_id=int(row.id),
        revision=int(row.desired_revision),
    )


def _install_listeners(session: OrmSession) -> None:
    if session.info.get(_LISTENERS_INSTALLED_KEY):
        return
    session.info[_LISTENERS_INSTALLED_KEY] = True
    event.listen(session, "after_transaction_create", _after_transaction_create)
    event.listen(session, "after_commit", _after_commit)
    event.listen(session, "after_rollback", _after_rollback)
    event.listen(session, "after_transaction_end", _after_transaction_end)


def _pending_refs(session: OrmSession) -> dict[int, KnowledgeFulltextDispatchRef]:
    return session.info.setdefault(_PENDING_REFS_KEY, {})


def _ensure_current_nested_snapshot(session: OrmSession) -> None:
    transaction = session.get_nested_transaction()
    if transaction is None:
        return
    snapshots: dict[int, dict[int, KnowledgeFulltextDispatchRef]] = session.info.setdefault(
        _NESTED_SNAPSHOTS_KEY,
        {},
    )
    snapshots.setdefault(id(transaction), dict(_pending_refs(session)))


def _after_transaction_create(session: OrmSession, transaction) -> None:
    if not transaction.nested:
        return
    snapshots: dict[int, dict[int, KnowledgeFulltextDispatchRef]] = session.info.setdefault(
        _NESTED_SNAPSHOTS_KEY,
        {},
    )
    snapshots[id(transaction)] = dict(_pending_refs(session))


def _after_commit(session: OrmSession) -> None:
    if session.in_nested_transaction():
        return
    refs = session.info.pop(_PENDING_REFS_KEY, {})
    session.info.pop(_NESTED_SNAPSHOTS_KEY, None)
    session.info.pop(_ROLLED_BACK_NESTED_KEY, None)
    for ref in sorted(refs.values(), key=lambda item: item.outbox_id):
        try:
            _publish_ref(
                outbox_id=ref.outbox_id,
                revision=ref.revision,
            )
        except Exception as exc:
            # The committed Outbox remains available for periodic compensation.
            logger.bind(
                outbox_id=ref.outbox_id,
                revision=ref.revision,
                dispatch_source="after_commit",
                status="publish_failed",
                error_type=type(exc).__name__,
            ).exception("knowledge fulltext immediate publish failed; beat will compensate")


def _after_rollback(session: OrmSession) -> None:
    transaction = session.get_nested_transaction()
    if transaction is not None:
        rolled_back: set[int] = session.info.setdefault(_ROLLED_BACK_NESTED_KEY, set())
        rolled_back.add(id(transaction))
        return
    session.info.pop(_PENDING_REFS_KEY, None)
    session.info.pop(_NESTED_SNAPSHOTS_KEY, None)
    session.info.pop(_ROLLED_BACK_NESTED_KEY, None)


def _after_transaction_end(session: OrmSession, transaction) -> None:
    if not transaction.nested:
        return
    snapshots: dict[int, dict[int, KnowledgeFulltextDispatchRef]] = session.info.get(
        _NESTED_SNAPSHOTS_KEY,
        {},
    )
    snapshot = snapshots.pop(id(transaction), None)
    rolled_back: set[int] = session.info.get(_ROLLED_BACK_NESTED_KEY, set())
    if id(transaction) in rolled_back:
        rolled_back.discard(id(transaction))
        session.info[_PENDING_REFS_KEY] = snapshot or {}


def _publish_ref(*, outbox_id: int, revision: int) -> None:
    from bisheng.worker.knowledge.fulltext_index import (
        publish_knowledge_fulltext_outbox,
    )

    publish_knowledge_fulltext_outbox(
        outbox_id=outbox_id,
        revision=revision,
        dispatch_source="after_commit",
    )
