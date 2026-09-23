"""Translate business-owned organization facts into transient F048 inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bisheng.core.openfga.authorization_model_f048 import build_authorization_model_f048
from bisheng.core.openfga.contextual import ContextualTupleProvider, dependent_relations
from bisheng.core.openfga.exceptions import FGAClientError
from bisheng.permission.domain.services.permission_action_service import PermissionFGADecisionPort


@dataclass(frozen=True, slots=True)
class ActorDepartmentContext:
    user_id: int
    subtree_department_ids: tuple[int, ...]


class DepartmentContextPort(Protocol):
    async def load(self, user_id: int) -> ActorDepartmentContext: ...


class PermissionRuntimeClientPort(PermissionFGADecisionPort, Protocol):
    """Client composition contract exposed without importing transport infrastructure."""

    @property
    def store_id(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    def configure_contextual_tuple_provider(
        self,
        provider: ContextualTupleProvider,
        *,
        transient_relations: frozenset[tuple[str, str]] = frozenset(),
        affected_relations: frozenset[tuple[str, str]] | None = None,
    ) -> None: ...


def configure_department_context(client: PermissionRuntimeClientPort, provider: DepartmentContextPort) -> None:
    """Install once at the composition root; no business imports or SQL here."""

    async def contextual_tuples(user: str) -> tuple[dict[str, str], ...]:
        identifier = user.removeprefix("user:")
        if not identifier.isdecimal() or int(identifier) <= 0 or str(int(identifier)) != identifier:
            raise FGAClientError("Invalid department context user")
        context = await provider.load(int(identifier))
        if context.user_id != int(identifier):
            raise FGAClientError("Department context principal mismatch")
        ids = sorted(set(context.subtree_department_ids))
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in ids):
            raise FGAClientError("Invalid department context identifier")
        return tuple({"user": user, "relation": "subtree_member", "object": f"department:{value}"} for value in ids)

    client.configure_contextual_tuple_provider(
        contextual_tuples,
        transient_relations=frozenset({("department", "subtree_member")}),
        affected_relations=dependent_relations(build_authorization_model_f048(), "department", "subtree_member"),
    )
