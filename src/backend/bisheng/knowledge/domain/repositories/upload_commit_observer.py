"""Shared native upload root-commit observation; this grants no resource rights."""

import asyncio
from weakref import WeakKeyDictionary, WeakSet, ref

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.resource_reference.application.contracts import TransactionIdentity


def root_transaction(transaction):
    while transaction.parent is not None:
        transaction = transaction.parent
    return transaction


def _required():
    # Preserve the existing File receipt error, including its business reason.
    raise KnowledgeOperationPlanConflictError(reason="upload_registration_original_root_commit_required")


class UploadCommitObserver:
    def __init__(self):
        self._roots = WeakKeyDictionary()

    def observe(self, transaction: TransactionIdentity):
        if not isinstance(transaction, TransactionIdentity) or not isinstance(transaction.session, AsyncSession):
            _required()
        transaction.assert_current(transaction.session)
        root = root_transaction(transaction.transaction)
        if root in self._roots:
            return
        state = self._roots[root] = {"commits": WeakSet(), "ended": False}
        native, root_ref = transaction.session.sync_session, ref(root)
        native_ref = ref(native)

        def committed(current):
            actual = current.get_nested_transaction() or current.get_transaction()
            if actual is not None and root_transaction(actual) is root_ref():
                state["commits"].add(actual)

        def remove(_finished=None):
            task_ref = state.pop("cleanup_task", None)
            task = task_ref() if task_ref else None
            if task is not None:
                task.remove_done_callback(remove)
            target = native_ref()
            if target is not None:
                for name, listener in (("after_commit", committed), ("after_transaction_end", ended)):
                    if sa.event.contains(target, name, listener):
                        sa.event.remove(target, name, listener)

        def ended(_current, actual):
            if actual is root_ref():
                state["ended"] = True
                # A later caller hook may yield through the async SQL bridge.
                # Only its owner-task completion ends the event dispatch stack.
                task = asyncio.current_task()
                if task is not None:
                    state["cleanup_task"] = ref(task)
                    task.add_done_callback(remove)

        state["retire"] = remove
        sa.event.listen(native, "after_commit", committed)
        sa.event.listen(native, "after_transaction_end", ended)

    def acknowledge(self, transactions: tuple[TransactionIdentity, ...]) -> None:
        if type(transactions) is not tuple:
            _required()
        retire = {}
        for identity in transactions:
            if not isinstance(identity, TransactionIdentity) or not isinstance(identity.session, AsyncSession):
                _required()
            transaction = identity.transaction
            state = self._roots.get(root_transaction(transaction))
            if not state or not state["ended"] or identity.session.in_transaction():
                _required()
            while transaction is not None:
                if transaction.is_active or transaction not in state["commits"]:
                    _required()
                transaction = transaction.parent
            retire[id(state)] = state["retire"]
        # The owning App invokes this only after awaited commit returns an ACK.
        for remove in retire.values():
            remove()
