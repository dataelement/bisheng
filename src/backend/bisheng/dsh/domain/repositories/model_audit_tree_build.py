"""Fenced, resumable shadow generations. Each call owns only a bounded SQL transaction."""

from datetime import timedelta
from uuid import uuid4

from sqlmodel import select

from bisheng.dsh.domain.models.model_audit_conversation import DshModelAuditConversation as Group
from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeNode as Node
from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreePath as Path
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.model_audit_hierarchy import AuditHierarchyRepository, tree_id, tree_now


class AuditTreeBuildRepository(AuditHierarchyRepository):
    def tree_step(self, *, owner=None, now=None, limit=100):
        tenant, now = require_tenant(), tree_now(now)
        if not 1 <= limit <= 100:
            raise ValueError("Tree step exceeds bounds")
        state = self.tree_state(create=True, lock=True)
        if owner and (owner != state.lease_owner or not state.lease_until or state.lease_until < now):
            return {"status": "STALE", "has_more": False}
        if not owner:
            if state.lease_owner and state.lease_until and state.lease_until > now:
                return {"status": "BUSY", "has_more": False}
            owner = str(uuid4())
        state.lease_owner, state.lease_until = owner, now + timedelta(seconds=60)
        state.failed = False
        if state.phase == "IDLE":
            if (
                state.active
                and state.revision == state.published_revision
                and state.summary_revision == state.published_summary_revision
            ):
                state.lease_owner, state.lease_until = None, None
                return {"status": "READY", "has_more": False}
            state.building = str(uuid4())
            state.build_revision, state.build_summary_revision = state.revision, state.summary_revision
            state.phase, state.after_key = "COPY", ""
        elif state.building and state.build_revision != state.revision:
            state.building, state.phase, state.after_key = None, "CLEANUP", ""
            state.lease_owner, state.lease_until = None, None
            self.session.add(state)
            return {"status": "RESTART", "has_more": True}
        elif state.phase == "COPY":
            groups = self.session.exec(
                select(Group)
                .where(Group.conversation_key > state.after_key)
                .order_by(Group.conversation_key)
                .limit(limit)
            ).all()
            for group in groups:
                # Verify copied identities through the existing scoped directory accessor.
                self.group(group.conversation_key)
                if group.request_count < 1 or not 0 <= group.abnormal_count <= group.request_count:
                    raise ValueError("Invalid source directory counters")
                self.session.add(
                    Node(
                        id=tree_id(tenant, state.building, group.conversation_key),
                        generation=state.building,
                        conversation_key=group.conversation_key,
                        conversation_id=group.conversation_id,
                        user_id=group.user_id,
                        declared_parent_key=group.declared_parent_key,
                        origin_state=group.origin_state,
                        relation_conflict=group.relation_conflict,
                        listed_at=group.listed_at,
                        last_request_at=group.last_request_at,
                        updated_at=group.updated_at,
                        request_count=group.request_count,
                        abnormal_count=group.abnormal_count,
                    )
                )
            state.after_key = groups[-1].conversation_key if groups else state.after_key
            if len(groups) < limit:
                state.phase, state.after_key = "RESOLVE", ""
        elif state.phase in {"RESOLVE", "AGGREGATE"}:
            nodes = self.session.exec(
                select(Node)
                .where(Node.generation == state.building, Node.conversation_key > state.after_key)
                .order_by(Node.conversation_key)
                .limit(limit)
            ).all()
            for node in nodes:
                if state.phase == "RESOLVE":
                    chain, reason = self._tree_chain(state.building, node)
                    node.relation_state = reason
                    node.parent_key = chain[1].conversation_key if len(chain) > 1 else ""
                    node.root_key = chain[-1].conversation_key
                    for depth, ancestor in enumerate(chain):
                        self.session.add(
                            Path(
                                id=tree_id(tenant, state.building, ancestor.conversation_key, node.conversation_key),
                                generation=state.building,
                                user_id=node.user_id,
                                ancestor_key=ancestor.conversation_key,
                                descendant_key=node.conversation_key,
                                depth=depth,
                            )
                        )
                else:
                    paths = self.session.exec(
                        select(Path)
                        .where(Path.generation == state.building, Path.descendant_key == node.conversation_key)
                        .limit(34)
                    ).all()
                    if len(paths) > 33:
                        raise ValueError("Tree path depth exceeds bounds")
                    for path in paths:
                        ancestor = self.tree_node(state.building, path.ancestor_key)
                        if ancestor is None or ancestor.user_id != node.user_id:
                            raise ValueError("Invalid tree ancestor")
                        ancestor.branch_count += node.request_count
                        ancestor.branch_abnormal += node.abnormal_count
                        self.session.add(ancestor)
                self.session.add(node)
            state.after_key = nodes[-1].conversation_key if nodes else state.after_key
            if len(nodes) < limit:
                state.phase, state.after_key = ("AGGREGATE" if state.phase == "RESOLVE" else "PUBLISH"), ""
        elif state.phase == "PUBLISH":
            # The locked state row serializes all structure revision changes and publication.
            readiness = self.readiness()
            if not readiness["status_ready"] or not readiness["name_ready"] or readiness["indexing_pending"]:
                raise ValueError("Audit facts are not ready for directory publication")
            from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request

            if self.session.exec(
                select(Request.request_id).where(Request.hierarchy_indexed.is_(False)).limit(1)
            ).first():
                state.building, state.phase = None, "CLEANUP"
            else:
                state.retired, state.active = state.active, state.building
                state.published_revision, state.published_summary_revision = (
                    state.build_revision,
                    state.build_summary_revision,
                )
                state.published_at = now
                state.building, state.phase = None, "CLEANUP"
        elif state.phase == "CLEANUP":
            retained = [g for g in (state.active, state.retired, state.building) if g]
            removed = 0
            for model in (Path, Node):
                statement = select(model)
                if retained:
                    statement = statement.where(model.generation.not_in(retained))
                obsolete = self.session.exec(statement.order_by(model.id).limit(limit)).all()
                removed += len(obsolete)
                for row in obsolete:
                    # ORM delete is restricted to verified tenant-scoped, exact disposable rows.
                    if row.tenant_id != tenant:
                        raise ValueError("Invalid cleanup scope")
                    self.session.delete(row)
            if not removed:
                state.phase, state.after_key = "IDLE", ""
                state.lease_owner, state.lease_until = None, None
                self.session.add(state)
                dirty = (
                    state.revision != state.published_revision
                    or state.summary_revision != state.published_summary_revision
                )
                return {"status": "READY" if state.active else "PREPARING", "has_more": dirty}
        self.session.add(state)
        self.session.flush()
        return {"status": state.phase, "owner": owner, "has_more": True}

    def _tree_chain(self, generation, node):
        chain, seen, current = [node], {node.conversation_key}, node
        for _ in range(33):
            if current.relation_conflict:
                return [node], "CONFLICT" if current is node else "PARENT_UNAVAILABLE"
            if current.origin_state != "subagent":
                return chain, "LINKED" if len(chain) > 1 else ("MAIN" if current.origin_state == "main" else "UNKNOWN")
            parent = current.declared_parent_key
            if not parent:
                return [node], "MISSING_PARENT" if current is node else "PARENT_UNAVAILABLE"
            if parent == current.conversation_key:
                return [node], "SELF_REFERENCE" if current is node else "PARENT_UNAVAILABLE"
            if parent in seen:
                return [node], "CYCLE"
            if len(chain) == 33:
                return [node], "DEPTH_LIMIT"
            target = self.tree_node(generation, parent)
            if target is None or target.user_id != node.user_id:
                return [node], "PARENT_UNAVAILABLE"
            seen.add(parent)
            chain.append(target)
            current = target
        return [node], "DEPTH_LIMIT"
