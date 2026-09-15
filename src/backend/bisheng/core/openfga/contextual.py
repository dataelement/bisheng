"""Request-local relationship inputs, independent of application domains."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps

from bisheng.core.openfga.exceptions import FGAClientError

ContextualTupleProvider = Callable[[str], Awaitable[tuple[dict[str, str], ...]]]
MAX_CONTEXTUAL_TUPLES = 100


@dataclass
class _ContextualScope:
    entries: dict[tuple[object, str], tuple[dict[str, str], ...]] = field(default_factory=dict)
    closed: bool = False


_scope: ContextVar[_ContextualScope | None] = ContextVar("fga_contextual_scope", default=None)


def contextual_operation(function):
    """Bound reuse across nested runtime calls in one authorization operation."""

    @wraps(function)
    async def wrapped(*args, **kwargs):
        with contextual_tuple_scope():
            return await function(*args, **kwargs)

    return wrapped


def dependent_relations(model: dict, target_type: str, target_relation: str) -> frozenset[tuple[str, str]]:
    """Find model relations that may consume the given relation's inputs."""
    parents: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for definition in model["type_definitions"]:
        name = definition["type"]
        metadata = (definition.get("metadata") or {}).get("relations", {})
        for relation, rewrite in definition.get("relations", {}).items():
            source = (name, relation)
            stack = [rewrite]
            while stack:
                item = stack.pop()
                targets = []
                if "this" in item:
                    targets.extend(
                        (ref["type"], ref["relation"])
                        for ref in metadata.get(relation, {}).get("directly_related_user_types", [])
                        if ref.get("relation")
                    )
                if "computedUserset" in item:
                    targets.append((name, item["computedUserset"]["relation"]))
                if "tupleToUserset" in item:
                    ttu = item["tupleToUserset"]
                    refs = metadata.get(ttu["tupleset"]["relation"], {}).get("directly_related_user_types", [])
                    targets.extend((ref["type"], ttu["computedUserset"]["relation"]) for ref in refs)
                for operation in ("union", "intersection"):
                    stack.extend(item.get(operation, {}).get("child", []))
                if "difference" in item:
                    stack.extend(item["difference"].values())
                for target in targets:
                    parents.setdefault(target, set()).add(source)
    affected = {(target_type, target_relation)}
    pending = list(affected)
    while pending:
        for parent in parents.get(pending.pop(), set()) - affected:
            affected.add(parent)
            pending.append(parent)
    return frozenset(affected)


@contextmanager
def contextual_tuple_scope():
    """Reuse completed inputs only inside an explicitly bounded operation."""
    existing = _scope.get()
    if existing is not None and not existing.closed:
        yield
        return
    scope = _ContextualScope()
    token = _scope.set(scope)
    try:
        yield
    finally:
        scope.closed = True
        scope.entries.clear()
        _scope.reset(token)


async def resolve_contextual_tuples(
    provider: ContextualTupleProvider | None,
    user: str,
    *,
    required: bool,
) -> tuple[dict[str, str], ...]:
    if not user.startswith("user:") or "#" in user or "*" in user:
        return ()
    if provider is None:
        if required:
            raise FGAClientError("Authorization relationship provider is not configured")
        return ()
    scope = _scope.get()
    key = (provider, user)
    if scope is not None and not scope.closed and key in scope.entries:
        return scope.entries[key]
    result = await provider(user)
    if len(result) > MAX_CONTEXTUAL_TUPLES:
        raise FGAClientError("Authorization context exceeds contextual tuple limit")
    # Never let an input provider assert facts about a different principal.
    if any(item.get("user") != user for item in result):
        raise FGAClientError("Authorization context principal mismatch")
    result = tuple(dict(item) for item in result)
    if scope is not None and not scope.closed:
        scope.entries[key] = result
    return result
