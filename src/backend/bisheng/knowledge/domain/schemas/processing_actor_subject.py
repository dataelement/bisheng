"""Pure subject facts from an accepted move origin, never live authorization."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from bisheng.permission.application.data_scope import DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL

_ORIGIN_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "actor_user_id",
        "space_id",
        "required_action",
        "entry_kind",
        "actor",
        "credential_reference",
    }
)
_ACTOR_FIELDS = frozenset(
    {"subject_type", "subject_id", "tenant_id", "super_admin", "tenant_admin_tenant_ids", "data_scope"}
)


def _positive_integer(value: object) -> bool:
    return type(value) is int and value > 0


@dataclass(frozen=True, slots=True)
class ProcessingActorSubject:
    subject_type: Literal["user", "service_account"]
    subject_id: int

    def __post_init__(self):
        if self.subject_type not in ("user", "service_account") or not _positive_integer(self.subject_id):
            raise ValueError("invalid processing actor subject")


def processing_actor_subject(
    reference: Mapping, *, tenant_id: int, actor_user_id: int, source_space_id: int, required_action="move"
) -> ProcessingActorSubject:
    """Read the original typed subject without restoring or expiring its credential.

    The nested actor tenant is the original home, whereas the outer tenant is
    the execution scope. The audit user is also independent of the subject.
    Current credential, selected-scope and authority checks remain in the
    existing capture/restore path; these facts do not authorize an operation.
    """
    if (
        required_action not in {"move", "delete", "upload_file"}
        or not all(_positive_integer(value) for value in (tenant_id, actor_user_id, source_space_id))
        or not isinstance(reference, Mapping)
        or set(reference) != _ORIGIN_FIELDS
        or type(reference["schema_version"]) is not int
        or reference["schema_version"] != 1
        or any(not _positive_integer(reference[key]) for key in ("tenant_id", "actor_user_id", "space_id"))
        or (reference["tenant_id"], reference["actor_user_id"], reference["space_id"])
        != (tenant_id, actor_user_id, source_space_id)
        or reference["required_action"] != required_action
        or reference["entry_kind"] not in ("web", "open_api")
        or not isinstance(reference["credential_reference"], Mapping)
    ):
        raise ValueError("invalid processing move origin")
    actor = reference["actor"]
    if (
        not isinstance(actor, Mapping)
        or set(actor) != _ACTOR_FIELDS
        or actor["subject_type"] not in ("user", "service_account")
        or not _positive_integer(actor["subject_id"])
        or not _positive_integer(actor["tenant_id"])
        or type(actor["super_admin"]) is not bool
        or actor["data_scope"] not in (DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL)
        or not isinstance(actor["tenant_admin_tenant_ids"], list)
        or any(not _positive_integer(value) for value in actor["tenant_admin_tenant_ids"])
    ):
        raise ValueError("invalid processing move actor facts")
    return ProcessingActorSubject(actor["subject_type"], actor["subject_id"])
