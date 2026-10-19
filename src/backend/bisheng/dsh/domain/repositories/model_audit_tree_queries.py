"""Indexed, bounded tree browsing. No body reads or request-table grouping."""

import base64
import json
from datetime import datetime
from hashlib import sha256
from time import monotonic

from sqlalchemy import and_, or_
from sqlmodel import select

from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request
from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeNode as Node
from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreePath as Path
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.model_audit_conversations import utc
from bisheng.dsh.domain.repositories.model_audit_tree_build import AuditTreeBuildRepository


class AuditTreeQueryRepository(AuditTreeBuildRepository):
    def _tree_matches(self, keys, filters):
        match = select(Request.request_id).where(
            Request.tenant_id == Node.tenant_id,
            Request.user_id == Node.user_id,
            Request.conversation_key == Node.conversation_key,
        )
        for key, value in filters.items():
            if key == "model_name":
                match = match.where(
                    Request.model_name_digest == sha256(value.encode()).hexdigest(), Request.model_name == value
                )
            elif key == "conversation_id":
                match = match.where(
                    Request.conversation_id_digest == sha256(value.encode()).hexdigest(),
                    Request.conversation_id == value,
                )
            elif key == "start_at":
                match = match.where(Request.started_at >= value)
            elif key == "end_at":
                match = match.where(Request.started_at < value)
            elif key in {"user_id", "request_id", "audit_status"}:
                match = match.where(getattr(Request, key) == value)
            else:
                raise ValueError("Unsupported tree filter")
        # IDs are generation-scoped; using conversation keys alone would join retired copies.
        return set(self.session.exec(select(Node.conversation_key).where(Node.id.in_(keys), match.exists())).all())

    def _tree_metadata(self, node, *, summary_ready, match_scope="SELF"):
        child = self.session.exec(
            select(Node.id).where(Node.generation == node.generation, Node.parent_key == node.conversation_key).limit(1)
        ).first()

        def summary(count, abnormal):
            return {
                "ready": summary_ready,
                "request_count": count if summary_ready else None,
                "abnormal_count": abnormal if summary_ready else None,
                "known_abnormal": abnormal > 0,
            }

        return {
            **{
                key: getattr(node, key)
                for key in (
                    "generation",
                    "conversation_key",
                    "conversation_id",
                    "user_id",
                    "parent_key",
                    "root_key",
                    "relation_state",
                    "request_count",
                    "abnormal_count",
                )
            },
            **{key: utc(getattr(node, key)) for key in ("listed_at", "last_request_at", "updated_at")},
            "has_children": child is not None,
            "match_scope": match_scope,
            "own_summary": summary(node.request_count, node.abnormal_count),
            "branch_summary": summary(node.branch_count, node.branch_abnormal),
            "summary_as_of": utc(node.create_time) if summary_ready else None,
        }

    def tree_page(self, *, parent_key="", generation=None, cursor=None, limit=20, scan_budget=1000, **filters):
        tenant = require_tenant()
        if not 1 <= limit <= 100 or not 1 <= scan_budget <= 1000:
            raise ValueError("Tree page exceeds bounds")
        filters = {key: value for key, value in filters.items() if value is not None}
        fingerprint = sha256(
            json.dumps([tenant, parent_key, filters], sort_keys=True, default=str, ensure_ascii=False).encode()
        ).hexdigest()
        before, candidate_key, descendant_after = None, None, ""
        if cursor:
            try:
                if len(cursor) > 2048:
                    raise ValueError()
                decoded = json.loads(base64.urlsafe_b64decode(cursor))
                if decoded["query"] != fingerprint or (generation and decoded["generation"] != generation):
                    raise ValueError()
                generation = decoded["generation"]
                if not isinstance(generation, str) or len(generation) != 36:
                    raise ValueError()
                before, candidate_key, descendant_after = (
                    decoded["before"],
                    decoded["candidate"],
                    decoded["descendant_after"],
                )
                for value in (candidate_key, descendant_after):
                    if value and (
                        not isinstance(value, str)
                        or len(value) != 64
                        or any(c not in "0123456789abcdef" for c in value)
                    ):
                        raise ValueError()
                if before is not None:
                    if len(before) != 2 or len(before[1]) != 64 or datetime.fromisoformat(before[0]).tzinfo:
                        raise ValueError()
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise ValueError("Invalid tree cursor") from None
        progress = {**self.readiness(), **self.tree_progress()}
        state = self.tree_state()
        generation = generation or (state.active if state else None)
        empty = {"items": [], "next_cursor": None, "scan_limited": False, "progress": progress}
        if not state or not state.active:
            if cursor or generation:
                progress["refresh_required"] = True
            return empty
        if generation not in {state.active, state.retired}:
            progress["refresh_required"] = True
            return empty
        if parent_key and self.tree_node(generation, parent_key) is None:
            raise LookupError("Tree node unavailable")
        if not progress["status_ready"] or not progress["name_ready"]:
            return empty
        summary_ready = progress["summary_ready"] and generation == state.active
        items, scanned, exhausted = [], 0, False
        deadline = monotonic() + 1
        while len(items) < limit and scanned < scan_budget and monotonic() < deadline:
            if candidate_key:
                candidate = self.tree_node(generation, candidate_key)
                if candidate is None or candidate.parent_key != parent_key:
                    raise ValueError("Invalid tree candidate")
            else:
                statement = select(Node).where(Node.generation == generation, Node.parent_key == parent_key)
                if filters.get("user_id"):
                    statement = statement.where(Node.user_id == filters["user_id"])
                if before:
                    started = datetime.fromisoformat(before[0])
                    statement = statement.where(
                        or_(
                            Node.listed_at < started, and_(Node.listed_at == started, Node.conversation_key < before[1])
                        )
                    )
                candidate = self.session.exec(
                    statement.order_by(Node.listed_at.desc(), Node.conversation_key.desc()).limit(1)
                ).first()
                if candidate is None:
                    exhausted = True
                    break
                candidate_key = candidate.conversation_key
            own_match = bool(self._tree_matches([candidate.id], filters))
            if own_match:
                # SELF means the node itself matches, not that descendants were exhaustively excluded.
                items.append(self._tree_metadata(candidate, summary_ready=summary_ready))
                scanned += 1
            else:
                paths = self.session.exec(
                    select(Path)
                    .where(
                        Path.generation == generation,
                        Path.user_id == candidate.user_id,
                        Path.ancestor_key == candidate_key,
                        Path.descendant_key > descendant_after,
                    )
                    .order_by(Path.descendant_key)
                    .limit(min(100, scan_budget - scanned))
                ).all()
                ids = [self.tree_node(generation, path.descendant_key) for path in paths]
                if any(node is None or node.user_id != candidate.user_id for node in ids):
                    raise ValueError("Invalid tree path ownership")
                matched = self._tree_matches([node.id for node in ids], filters) if ids else set()
                scanned += max(1, len(paths))
                if matched:
                    items.append(self._tree_metadata(candidate, summary_ready=summary_ready, match_scope="DESCENDANT"))
                elif paths:
                    descendant_after = paths[-1].descendant_key
                    continue
            before = [candidate.listed_at.isoformat(), candidate_key]
            candidate_key, descendant_after = None, ""
        next_cursor = None
        if not exhausted:
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "query": fingerprint,
                        "generation": generation,
                        "before": before,
                        "candidate": candidate_key,
                        "descendant_after": descendant_after,
                    }
                ).encode()
            ).decode()
        names = self.user_names(item["user_id"] for item in items)
        return {
            "items": [{**item, "user_name": names.get(item["user_id"])} for item in items],
            "next_cursor": next_cursor,
            "scan_limited": bool(next_cursor and len(items) < limit),
            "progress": progress,
        }

    def tree_location(self, key, *, generation=None):
        require_tenant()
        state = self.tree_state()
        generation = generation or (state.active if state else None)
        if not state or not generation or generation not in {state.active, state.retired}:
            return {"items": [], "progress": {**self.tree_progress(), "refresh_required": True}}
        node = self.tree_node(generation, key)
        if node is None:
            raise LookupError("Tree node unavailable")
        paths = self.session.exec(
            select(Path)
            .where(Path.generation == generation, Path.descendant_key == key, Path.user_id == node.user_id)
            .order_by(Path.depth.desc())
            .limit(34)
        ).all()
        if not paths or len(paths) > 33:
            raise ValueError("Invalid tree location")
        result = [self.tree_node(generation, path.ancestor_key) for path in paths]
        if any(ancestor is None or ancestor.user_id != node.user_id for ancestor in result):
            raise ValueError("Invalid tree location scope")
        names = self.user_names([node.user_id])
        return {
            "items": [
                {**self._tree_metadata(ancestor, summary_ready=False), "user_name": names.get(node.user_id)}
                for ancestor in result
            ],
            "progress": self.tree_progress(),
        }
