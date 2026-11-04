"""Server-owned operation requirements; these are not granted permissions."""

from enum import StrEnum
from typing import Literal, TypedDict

APP_ACTIONS = ("use", "edit", "manage_permission", "delete", "publish", "unpublish")
MANAGEMENT_ACTIONS = frozenset(APP_ACTIONS) - {"use"}


class AppOperation(StrEnum):
    MANAGEMENT_READ = "management_read"
    CONTENT_READ = "content_read"
    METADATA_EDIT = "metadata_edit"
    LOG_READ = "log_read"
    DATA_READ = "data_read"
    DATA_EDIT = "data_edit"
    SECRET_READ = "secret_read"
    SECRET_EDIT = "secret_edit"
    PRIVATE_DEPENDENCY = "private_dependency"
    SNAPSHOT_READ = "snapshot_read"
    RESTORE = "restore"
    CONFIG_RESTART = "config_restart"
    RELEASE_SUBMIT = "release_submit"
    APPROVED_START = "approved_start"
    WITHDRAW = "withdraw"
    STOP = "stop"
    DESTROY = "destroy"
    GRANT_MANAGE = "grant_manage"
    AUDIT_READ = "audit_read"
    MANAGEMENT_PREVIEW = "management_preview"


_REQUIREMENTS = {
    AppOperation.CONTENT_READ: ("edit",),
    AppOperation.METADATA_EDIT: ("edit",),
    AppOperation.LOG_READ: ("edit",),
    AppOperation.DATA_READ: ("edit",),
    AppOperation.DATA_EDIT: ("edit",),
    AppOperation.SECRET_READ: ("edit",),
    AppOperation.SECRET_EDIT: ("edit",),
    AppOperation.PRIVATE_DEPENDENCY: ("edit",),
    AppOperation.SNAPSHOT_READ: ("edit",),
    AppOperation.RESTORE: ("edit",),
    AppOperation.CONFIG_RESTART: ("edit", "publish"),
    AppOperation.RELEASE_SUBMIT: ("edit", "publish"),
    AppOperation.APPROVED_START: ("publish",),
    AppOperation.WITHDRAW: ("publish",),
    AppOperation.STOP: ("unpublish",),
    AppOperation.DESTROY: ("delete",),
    AppOperation.GRANT_MANAGE: ("manage_permission",),
    AppOperation.AUDIT_READ: ("edit",),
    AppOperation.MANAGEMENT_PREVIEW: ("edit",),
}


def required_actions(operation: AppOperation | str, *, resume: bool = False) -> tuple[str, ...]:
    purpose = AppOperation(operation)
    if purpose is AppOperation.RESTORE and resume:
        return ("edit", "publish")
    if purpose not in _REQUIREMENTS:
        raise ValueError("The operation has no all-of action requirement")
    return _REQUIREMENTS[purpose]


class AuthorizationActor(TypedDict):
    subject_type: Literal["user", "service_account"]
    subject_id: int
    tenant_id: int


class UserAuthorizationContext(TypedDict):
    schema: Literal[1]
    origin_kind: Literal["user_request"]
    actor: AuthorizationActor
    credential_ref: dict
    mode: str | None
    self_review_user_id: int
    purpose: str
    required_actions: list[str]
    target: dict


class SystemRecoveryContext(TypedDict):
    schema: Literal[1]
    origin_kind: Literal["system_recovery"]
    purpose: Literal["system_recovery"]
    source: dict
    target: dict
