"""Bounded original SPACE membership facts for the private M2 inventory.

Member has no tenant column: scoped pages use an exact, physically owned
type-0/3 Root to classify its business ID. Conflicting roles, duplicate users and
inactive sources remain facts. These reads grant no authority or membership
repair. The separate global gate proves canonical original SPACE parents.
"""

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.models.space_channel_member import BusinessTypeEnum, SpaceChannelMember
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    is_tenant_filter_bypassed,
    strict_tenant_filter,
)
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.repositories.unification_inventory_repository import InventoryPage
from bisheng.knowledge.domain.schemas.unification_conversion import ResourceConversionCommand
from bisheng.knowledge.domain.schemas.unification_space_membership import creator_membership_template
from bisheng.knowledge.domain.services.unification_fingerprints import digest
from bisheng.resource_reference.application.contracts import TransactionIdentity

HEADER_COLUMNS = ("knowledge_id", "tenant_id", "knowledge_type", "creator_user_id", "member_count")
MEMBER_COLUMNS = (
    "id",
    "business_id",
    "business_type",
    "user_id",
    "user_role",
    "status",
    "membership_source",
    "department_admin_promoted_from_role",
    "relation",
    "grant_subject_type",
    "grant_subject_id",
    "grant_relation",
    "grant_include_children",
    "grant_model_id",
    "grant_binding_key",
    "is_pinned",
    "create_time",
    "update_time",
)


@dataclass(frozen=True, slots=True)
class SpaceMembershipHeader:
    knowledge_id: int
    tenant_id: int
    knowledge_type: int
    creator_user_id: int | None
    member_count: int


@dataclass(frozen=True, slots=True, repr=False)
class SpaceMembershipRow:
    tenant_id: int
    knowledge_id: int
    id: int
    business_id: str
    business_type: str
    user_id: int
    user_role: str
    status: str
    membership_source: str
    department_admin_promoted_from_role: str | None
    relation: str | None
    grant_subject_type: str | None
    grant_subject_id: int | None
    grant_relation: str | None
    grant_include_children: bool
    grant_model_id: str | None
    grant_binding_key: str | None
    is_pinned: bool
    create_time: datetime | None
    update_time: datetime | None


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"unification_space_membership_{reason}")


def _scope(session):
    tenant = get_current_tenant_id()
    if (
        not isinstance(session, AsyncSession)
        or not session.in_transaction()
        or type(tenant) is not int
        or tenant <= 0
        or is_tenant_filter_bypassed()
    ):
        _blocked("native_transaction_scope_required")
    return tenant


def _positive(value):
    return type(value) is int and value > 0


def _bounds(after_id, limit):
    if type(limit) is not int or not 1 <= limit <= 200 or (after_id is not None and not _positive(after_id)):
        _blocked("invalid_page")


def _current(session, tenant, transaction):
    if _scope(session) != tenant:
        _blocked("tenant_changed")
    try:
        transaction.assert_current(session)
    except (TypeError, ValueError) as error:
        raise KnowledgeOperationPlanConflictError(reason="unification_space_membership_transaction_changed") from error


class UnificationSpaceMembershipRepository:
    async def _alock_conversion_sets(self, session, *, roots, commands, current):
        current()
        tenant, transaction = _scope(session), TransactionIdentity.capture(session)
        selected = tuple(cmd for cmd in commands if type(cmd) is ResourceConversionCommand)
        by_id = {cmd.knowledge_id: cmd for cmd in selected}
        if len(by_id) != len(selected) or len(by_id) > 200:
            _blocked("conversion_duplicate_or_large_roots")
        for ident, cmd in by_id.items():
            row = roots.get(ident)
            if (
                row is None
                or row["tenant_id"] != tenant
                or row["type"] not in (0, 3)
                or not _positive(cmd.creator_user_id)
                or type(row["user_id"]) is not int
                or row["user_id"] != cmd.creator_user_id
            ):
                _blocked("conversion_root_scope_changed")
        groups = {ident: [] for ident in by_id}
        if not groups:
            return groups
        canonical = {str(ident): ident for ident in by_id}
        member, after = SpaceChannelMember.__table__.c, None
        while True:
            query = select(*(member[name] for name in MEMBER_COLUMNS)).where(
                member.business_type == BusinessTypeEnum.SPACE, member.business_id.in_(tuple(canonical))
            )
            if after is not None:
                query = query.where(member.id > after)
            current()
            rows = await self._read(
                session, query.order_by(member.id).limit(201).with_for_update(), tenant, transaction
            )
            current()
            for row in rows[:200]:
                if row["business_id"] not in canonical or not _positive(row["id"]):
                    _blocked("conversion_member_scope_changed")
                ident = canonical[row["business_id"]]
                groups[ident].append(
                    SpaceMembershipRow(
                        tenant_id=tenant,
                        knowledge_id=ident,
                        **{
                            name: row[name].value if isinstance(row[name], Enum) else row[name]
                            for name in MEMBER_COLUMNS
                        },
                    )
                )
            if len(rows) <= 200:
                return {ident: tuple(values) for ident, values in groups.items()}
            after = rows[199]["id"]

    @staticmethod
    def _conversion_facts(command, root, members):
        if (
            type(command) is not ResourceConversionCommand
            or not _positive(command.creator_user_id)
            or type(command.before_member_count) is not int
            or command.before_member_count < 0
            or type(command.membership_action) is not str
            or command.membership_action not in {"insert", "keep"}
            or any(
                type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
                for value in (command.before_member_digest, command.creator_template_digest)
            )
            or root["tenant_id"] != command.tenant_id
            or root["id"] != command.knowledge_id
            or type(root["user_id"]) is not int
            or root["user_id"] != command.creator_user_id
            or type(members) is not tuple
        ):
            _blocked("conversion_creator_command_invalid")
        if command.membership_action == "insert":
            if command.existing_creator_member_id is not None:
                _blocked("conversion_insert_identity_invalid")
            template = creator_membership_template(
                knowledge_id=command.knowledge_id,
                creator_user_id=command.creator_user_id,
                planned_at=command.creator_planned_at,
            )
            if digest(template) != command.creator_template_digest:
                _blocked("conversion_template_changed")
        elif not _positive(command.existing_creator_member_id) or command.creator_planned_at is not None:
            _blocked("conversion_keep_identity_invalid")
        owners, other_creator, previous = [], False, 0
        for row in members:
            if (
                type(row) is not SpaceMembershipRow
                or not _positive(row.id)
                or row.id <= previous
                or (row.tenant_id, row.knowledge_id, row.business_id, row.business_type)
                != (command.tenant_id, command.knowledge_id, str(command.knowledge_id), "space")
            ):
                _blocked("conversion_member_facts_invalid")
            previous = row.id
            if row.user_id == command.creator_user_id:
                owners.append(row)
            elif row.user_role == "creator":
                other_creator = True
        return owners, other_creator, digest(tuple(asdict(row) for row in members))

    def _assert_conversion_before(self, *, command, root, members):
        owners, other, actual = self._conversion_facts(command, root, members)
        if (
            root["type"] != 0
            or len(members) != command.before_member_count
            or actual != command.before_member_digest
            or other
        ):
            _blocked("conversion_member_before_changed")
        if command.membership_action == "insert":
            if owners:
                _blocked("conversion_owner_already_exists")
        elif (
            len(owners) != 1
            or (owners[0].id, owners[0].user_role, owners[0].status)
            != (command.existing_creator_member_id, "creator", "ACTIVE")
            or digest({name: getattr(owners[0], name) for name in MEMBER_COLUMNS if name != "id"})
            != command.creator_template_digest
        ):
            _blocked("conversion_keep_member_changed")

    async def _aapply_conversion_member(self, session, *, command, current):
        current()
        if session.new or session.dirty or session.deleted:
            _blocked("conversion_caller_pending")
        if command.membership_action == "keep":
            return command.existing_creator_member_id
        member = SpaceChannelMember(
            **creator_membership_template(
                knowledge_id=command.knowledge_id,
                creator_user_id=command.creator_user_id,
                planned_at=command.creator_planned_at,
            )
        )
        session.add(member)
        current()
        await session.flush()
        current()
        if not _positive(member.id):
            _blocked("conversion_insert_pk_missing")
        return member.id

    def _assert_conversion_after(self, *, command, root, members, expected_member_id=None):
        owners, other, actual = self._conversion_facts(command, root, members)
        if root["type"] != 3 or len(owners) != 1 or other:
            _blocked("conversion_creator_after_invalid")
        owner = owners[0]
        owner_id = owner.id
        if (
            (owner.user_role, owner.status) != ("creator", "ACTIVE")
            or (expected_member_id is not None and owner_id != expected_member_id)
            or digest({name: getattr(owner, name) for name in MEMBER_COLUMNS if name != "id"})
            != command.creator_template_digest
        ):
            _blocked("conversion_creator_after_changed")
        if command.membership_action == "keep":
            if (
                owner_id != command.existing_creator_member_id
                or len(members) != command.before_member_count
                or actual != command.before_member_digest
            ):
                _blocked("conversion_keep_after_changed")
        elif (
            len(members) != command.before_member_count + 1
            or digest(tuple(asdict(row) for row in members if row.id != owner_id)) != command.before_member_digest
        ):
            _blocked("conversion_insert_after_changed")
        return owner_id, actual

    @staticmethod
    async def _global_read(session, statement, tenant, transaction):
        _current(session, tenant, transaction)
        with session.no_autoflush, strict_tenant_filter(), bypass_tenant_filter():
            rows = tuple((await session.execute(statement)).mappings())
        _current(session, tenant, transaction)
        return rows

    async def avalidate_global_integrity(self, session: AsyncSession) -> None:
        tenant = _scope(session)
        transaction = TransactionIdentity.capture(session)
        member, root = SpaceChannelMember.__table__.c, Knowledge.__table__.c
        parent_tenant = Tenant.__table__.alias("m2_member_parent_tenant")
        after = None
        while True:
            query = select(member.id, member.business_id).where(member.business_type == BusinessTypeEnum.SPACE)
            if after is not None:
                query = query.where(member.id > after)
            rows = await self._global_read(session, query.order_by(member.id).limit(201), tenant, transaction)
            selected = rows[:200]
            if not selected:
                return
            ids = []
            for row in selected:
                value = row["business_id"]
                if type(value) is not str or re.fullmatch(r"[1-9][0-9]{0,18}", value) is None or int(value) > 2**63 - 1:
                    _blocked("global_business_id_invalid")
                ids.append(int(value))
            ids = tuple(dict.fromkeys(ids))
            parents = await self._global_read(
                session,
                select(
                    root.id.label("knowledge_id"),
                    root.tenant_id,
                    root.type.label("knowledge_type"),
                    parent_tenant.c.id.label("original_tenant_id"),
                )
                .select_from(Knowledge.__table__.outerjoin(parent_tenant, parent_tenant.c.id == root.tenant_id))
                .where(root.id.in_(ids)),
                tenant,
                transaction,
            )
            if {row["knowledge_id"] for row in parents} != set(ids) or any(
                not _positive(row["tenant_id"])
                or row["original_tenant_id"] != row["tenant_id"]
                or type(row["knowledge_type"]) is not int
                or row["knowledge_type"] not in (0, 1, 2, 3)
                for row in parents
            ):
                _blocked("global_parent_invalid")
            if len(rows) <= 200:
                return
            after = selected[-1]["id"]

    @staticmethod
    async def _read(session, statement, tenant, transaction):
        _current(session, tenant, transaction)
        with session.no_autoflush, strict_tenant_filter():
            rows = tuple((await session.execute(statement)).mappings())
        _current(session, tenant, transaction)
        return rows

    @staticmethod
    def _roots(tenant):
        root = Knowledge.__table__.c
        return select(
            root.id.label("knowledge_id"),
            root.tenant_id,
            root.type.label("knowledge_type"),
            root.user_id.label("creator_user_id"),
        ).where(root.tenant_id == tenant, root.type.in_((0, 3)))

    async def apage_headers(
        self, session: AsyncSession, *, after_id: int | None = None, limit: int = 200
    ) -> InventoryPage[SpaceMembershipHeader]:
        tenant = _scope(session)
        _bounds(after_id, limit)
        transaction = TransactionIdentity.capture(session)
        query = self._roots(tenant)
        if after_id is not None:
            query = query.where(Knowledge.__table__.c.id > after_id)
        roots = await self._read(
            session, query.order_by(Knowledge.__table__.c.id).limit(limit + 1), tenant, transaction
        )
        selected = roots[:limit]
        if not selected:
            return InventoryPage((), None)
        member = SpaceChannelMember.__table__.c
        counts = await self._read(
            session,
            select(member.business_id, func.count().label("member_count"))
            .where(
                member.business_type == BusinessTypeEnum.SPACE,
                member.business_id.in_(tuple(str(row["knowledge_id"]) for row in selected)),
            )
            .group_by(member.business_id),
            tenant,
            transaction,
        )
        by_id = {row["business_id"]: row["member_count"] for row in counts}
        items = tuple(
            SpaceMembershipHeader(**row, member_count=by_id.get(str(row["knowledge_id"]), 0)) for row in selected
        )
        return InventoryPage(items, items[-1].knowledge_id if len(roots) > limit else None)

    async def apage_members(
        self,
        session: AsyncSession,
        *,
        knowledge_ids: tuple[int, ...],
        after_id: int | None = None,
        limit: int = 200,
    ) -> InventoryPage[SpaceMembershipRow]:
        tenant = _scope(session)
        _bounds(after_id, limit)
        if (
            type(knowledge_ids) is not tuple
            or len(knowledge_ids) > 200
            or any(not _positive(ident) for ident in knowledge_ids)
            or len(set(knowledge_ids)) != len(knowledge_ids)
        ):
            _blocked("invalid_exact_roots")
        if not knowledge_ids:
            return InventoryPage((), None)
        transaction = TransactionIdentity.capture(session)
        roots = await self._read(
            session,
            self._roots(tenant).where(Knowledge.__table__.c.id.in_(knowledge_ids)),
            tenant,
            transaction,
        )
        if {row["knowledge_id"] for row in roots} != set(knowledge_ids):
            _blocked("original_root_missing_or_not_owned")
        by_id = {str(row["knowledge_id"]): row["knowledge_id"] for row in roots}
        member = SpaceChannelMember.__table__.c
        query = select(*(member[name] for name in MEMBER_COLUMNS)).where(
            member.business_type == BusinessTypeEnum.SPACE, member.business_id.in_(tuple(by_id))
        )
        if after_id is not None:
            query = query.where(member.id > after_id)
        rows = await self._read(session, query.order_by(member.id).limit(limit + 1), tenant, transaction)
        items = tuple(
            SpaceMembershipRow(
                tenant_id=tenant,
                knowledge_id=by_id[row["business_id"]],
                **{name: row[name].value if isinstance(row[name], Enum) else row[name] for name in MEMBER_COLUMNS},
            )
            for row in rows[:limit]
        )
        return InventoryPage(items, items[-1].id if len(rows) > limit else None)
