"""Fold immutable client declarations once, separately from body/state projection."""

from datetime import UTC, datetime
from hashlib import sha256

from sqlmodel import select

from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request
from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeNode as Node
from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeState as State
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.infrastructure.model_audit_codec import conversation_key


def tree_id(*parts):
    return sha256("\x00".join(str(p) for p in parts).encode()).hexdigest()


def tree_now(value=None):
    value = value or datetime.now(UTC)
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


class AuditHierarchyRepository:
    def tree_pending_tenants(self, *, cursor=0, include_group_pending=False):
        from sqlalchemy import or_

        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.database.models.tenant import Tenant

        # Tenant directory drives the scan: no DISTINCT/GROUP BY on the large request table.
        request_dirty = Request.hierarchy_indexed.is_(False)
        if include_group_pending:
            request_dirty = or_(request_dirty, Request.group_index_pending.is_(True))
        pending = select(Request.request_id).where(Request.tenant_id == Tenant.id, request_dirty)
        dirty = select(State.tenant_id).where(
            State.tenant_id == Tenant.id,
            or_(
                State.phase != "IDLE",
                State.revision != State.published_revision,
                State.summary_revision != State.published_summary_revision,
                State.safety_summary_revision != State.published_safety_summary_revision,
                State.failed.is_(True),
            ),
        )
        with bypass_tenant_filter():
            return self.session.exec(
                select(Tenant.id)
                .where(Tenant.id > cursor, or_(pending.exists(), dirty.exists()))
                .order_by(Tenant.id)
                .limit(100)
            ).all()

    def tree_state(self, *, create=False, lock=False):
        tenant = require_tenant()
        state = self.one(State, lock=lock)
        if state is None and create:
            state = State(tenant_id=tenant)
            self.session.add(state)
            self.session.flush()
        return state

    def tree_dirty(self, *, structure=False):
        state = self.tree_state(create=True, lock=True)
        state.summary_revision += 1
        state.revision += int(structure)
        self.session.add(state)

    def tree_node(self, generation, key):
        node = self.one(Node, Node.id == tree_id(require_tenant(), generation, key))
        if node and conversation_key(require_tenant(), node.user_id, node.conversation_id) != key:
            raise ValueError("Invalid tree identity binding")
        return node

    def fold_hierarchy_batch(self, *, limit=100, apply=True):
        require_tenant()
        if not 1 <= limit <= 100:
            raise ValueError("Tree batch exceeds bounds")
        statement = (
            select(Request).where(Request.hierarchy_indexed.is_(False)).order_by(Request.request_id).limit(limit)
        )
        if apply:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        rows = self.session.exec(statement).all()
        if apply:
            for row in rows:
                if row.conversation_key:
                    group = self.group(row.conversation_key, lock=True)
                    if group is None:
                        self.project_request(row.request_id)
                        group = self.group(row.conversation_key, lock=True)
                    if group is None:
                        raise ValueError("Prepare audit presentation before hierarchy")
                    before = (
                        group.origin_state,
                        group.declared_parent_key,
                        group.parent_declaration_missing,
                        group.relation_conflict,
                    )
                    origin = row.session_origin if row.session_origin in {"main", "subagent"} else None
                    if origin:
                        if group.origin_state == "UNKNOWN":
                            group.origin_state = origin
                        elif group.origin_state != origin:
                            group.relation_conflict = True
                        if origin == "subagent":
                            parent = row.parent_conversation_id
                            if parent:
                                key = conversation_key(require_tenant(), row.user_id, parent)
                                if group.declared_parent_key and group.declared_parent_key != key:
                                    group.relation_conflict = True
                                elif not group.declared_parent_key:
                                    group.declared_parent_key = key
                            else:
                                group.parent_declaration_missing = True
                    after = (
                        group.origin_state,
                        group.declared_parent_key,
                        group.parent_declaration_missing,
                        group.relation_conflict,
                    )
                    if before != after:
                        self.tree_dirty(structure=True)
                    self.session.add(group)
                row.hierarchy_indexed = True
                self.session.add(row)
        return {"examined": len(rows), "has_more": len(rows) == limit, "apply": apply}

    def tree_progress(self):
        state = self.tree_state()
        pending = (
            self.session.exec(select(Request.request_id).where(Request.hierarchy_indexed.is_(False)).limit(1)).first()
            is not None
        )
        counts_pending = (
            self.session.exec(select(Request.request_id).where(Request.group_index_pending.is_(True)).limit(1)).first()
            is not None
        )
        dirty = bool(
            state
            and (
                state.revision != state.published_revision
                or state.summary_revision != state.published_summary_revision
                or state.safety_summary_revision != state.published_safety_summary_revision
                or counts_pending
            )
        )
        return {
            "hierarchy_available": True,
            "hierarchy_ready": bool(state and state.active),
            "generation": state.active if state else None,
            "phase": "FAILED"
            if state and state.failed
            else (
                "UPDATING"
                if state and state.active and (dirty or pending)
                else ("READY" if state and state.active else "PREPARING")
            ),
            "summary_ready": bool(state and state.active and not dirty and not pending),
            "refresh_required": False,
        }
