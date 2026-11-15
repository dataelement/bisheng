"""Close original Member facts and frozen commands before formal conversion.

This verifier grants no authority. It retains one Root's original rows at a
time, lightweight Root/creator summaries and a unique physical Member-ID set.
"""

from dataclasses import dataclass
from datetime import datetime

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_inventory_codec import InventoryRecord
from bisheng.knowledge.domain.repositories.unification_space_membership_repository import MEMBER_COLUMNS
from bisheng.knowledge.domain.schemas.unification_space_membership import creator_membership_template
from bisheng.knowledge.domain.services.unification_fingerprints import digest

_RELEVANT = {
    "resource": ("baseline", "resources"),
    "creator": ("baseline", "control"),
    "space_membership_header": ("baseline", "control"),
    "space_member": ("baseline", "control"),
    "resource_conversion": ("plan", "conversion"),
}
_COMMAND_FIELDS = (
    "creator_user_id",
    "membership_action",
    "before_member_count",
    "before_member_digest",
    "existing_creator_member_id",
    "creator_template_digest",
    "creator_planned_at",
)


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="membership_inventory_" + reason)


def _raw(data):
    value = {name: item for name, item in data.items() if name != "row_digest"}
    if "row_digest" in data and data["row_digest"] != digest(value):
        _blocked("row_digest_changed")
    return value


@dataclass(frozen=True, slots=True)
class _Summary:
    header: dict
    before_digest: str
    owner_count: int
    owner_id: int | None
    owner_role: str | None
    owner_status: str | None
    owner_template_digest: str | None
    other_creator: bool


class MembershipInventoryVerifier:
    def __init__(self):
        self.resources, self.creators, self.headers, self.commands = {}, {}, {}, {}
        self._member_ids, self._members = set(), []
        self._active, self._finished = None, False

    def _close_header(self):
        header = self._active
        if header is None:
            return
        if len(self._members) != header["member_count"]:
            _blocked("incomplete_member_set")
        owner, owner_count, other_creator = None, 0, False
        for row in self._members:
            if row["user_id"] == header["creator_user_id"]:
                owner, owner_count = row, owner_count + 1
            elif row["user_role"] == "creator":
                other_creator = True
        self.headers[(header["tenant_id"], header["knowledge_id"])] = _Summary(
            header,
            digest(self._members),
            owner_count,
            None if owner is None else owner["id"],
            None if owner is None else owner["user_role"],
            None if owner is None else owner["status"],
            None if owner is None else digest({name: owner[name] for name in MEMBER_COLUMNS if name != "id"}),
            other_creator,
        )
        self._active, self._members = None, []

    def observe(self, *, kind, section, tenant_id, record):
        if self._finished or type(record) is not InventoryRecord:
            _blocked("invalid_stream")
        tag = record.record_type
        if tag not in _RELEVANT:
            return
        data = record.data
        if (
            (kind, section) != _RELEVANT[tag]
            or type(tenant_id) is not int
            or tenant_id <= 0
            or (tag != "creator" and data.get("tenant_id") != tenant_id)
        ):
            _blocked("record_scope")
        raw = _raw(data)
        if tag == "resource":
            key = tenant_id, data["id"]
            if key in self.resources or data["type"] not in (0, 1, 2, 3):
                _blocked("duplicate_or_unknown_resource")
            self.resources[key] = data["type"], data["user_id"]
        elif tag == "creator":
            key = tenant_id, data["user_id"]
            previous = self.creators.get(key)
            if previous is not None and previous != raw:
                _blocked("creator_changed")
            self.creators[key] = raw
        elif tag == "space_membership_header":
            self._close_header()
            key = tenant_id, data["knowledge_id"]
            if key in self.headers or data["knowledge_type"] not in (0, 3):
                _blocked("duplicate_or_invalid_header")
            self._active = raw
            if raw["member_count"] == 0:
                self._close_header()
        elif tag == "space_member":
            header = self._active
            if (
                header is None
                or header["tenant_id"] != tenant_id
                or data["knowledge_id"] != header["knowledge_id"]
                or data["business_id"] != str(header["knowledge_id"])
                or data["business_type"] != "space"
                or data["id"] in self._member_ids
                or (self._members and data["id"] <= self._members[-1]["id"])
                or data["user_role"] not in {"creator", "admin", "member"}
                or data["status"] not in {"ACTIVE", "PENDING", "REJECTED"}
                or len(self._members) >= header["member_count"]
            ):
                _blocked("member_identity_or_order")
            for name in ("create_time", "update_time"):
                if data[name] is not None:
                    try:
                        if datetime.fromisoformat(data[name]).isoformat() != data[name]:
                            _blocked("member_time")
                    except ValueError as error:
                        raise KnowledgeOperationPlanConflictError(reason="membership_inventory_member_time") from error
            self._member_ids.add(data["id"])
            self._members.append(raw)
            if len(self._members) == header["member_count"]:
                self._close_header()
        else:
            key = tenant_id, data["knowledge_id"]
            if key in self.commands or not set(_COMMAND_FIELDS) <= data.keys():
                _blocked("duplicate_or_incomplete_command")
            self.commands[key] = {name: data[name] for name in _COMMAND_FIELDS}

    def _command(self, key, summary):
        header, command = summary.header, self.commands[key]
        creator = self.creators.get((key[0], header["creator_user_id"]))
        if (
            type(header["creator_user_id"]) is not int
            or header["creator_user_id"] <= 0
            or creator is None
            or creator["exists"] is not True
            or command["creator_user_id"] != header["creator_user_id"]
            or command["before_member_count"] != header["member_count"]
            or command["before_member_digest"] != summary.before_digest
            or summary.other_creator
            or summary.owner_count > 1
        ):
            _blocked("creator_or_original_set_changed")
        if command["membership_action"] == "insert":
            if summary.owner_count or command["existing_creator_member_id"] is not None:
                _blocked("insert_conflict")
            try:
                planned = datetime.fromisoformat(command["creator_planned_at"])
            except (TypeError, ValueError) as error:
                raise KnowledgeOperationPlanConflictError(reason="membership_inventory_insert_time") from error
            template = creator_membership_template(
                knowledge_id=key[1], creator_user_id=header["creator_user_id"], planned_at=planned
            )
            expected = digest(template)
        elif command["membership_action"] == "keep":
            if (
                summary.owner_count != 1
                or summary.owner_role != "creator"
                or summary.owner_status != "ACTIVE"
                or command["existing_creator_member_id"] != summary.owner_id
                or command["creator_planned_at"] is not None
            ):
                _blocked("keep_conflict")
            expected = summary.owner_template_digest
        else:
            _blocked("invalid_membership_action")
        if expected != command["creator_template_digest"]:
            _blocked("template_changed")

    def finish(self):
        if self._finished:
            _blocked("already_finished")
        self._close_header()
        expected_headers = {key for key, (kind, _) in self.resources.items() if kind in (0, 3)}
        expected_commands = {key for key, (kind, _) in self.resources.items() if kind == 0}
        if set(self.headers) != expected_headers or set(self.commands) != expected_commands:
            _blocked("incomplete_root_closure")
        for key, summary in self.headers.items():
            if self.resources[key] != (summary.header["knowledge_type"], summary.header["creator_user_id"]):
                _blocked("header_resource_changed")
            if summary.header["knowledge_type"] == 0:
                self._command(key, summary)
        self._finished = True
