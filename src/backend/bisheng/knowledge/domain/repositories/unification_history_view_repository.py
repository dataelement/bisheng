"""Private F118 delta facts; no database/session proxy or write authority.

Only changed rows live in this disposable index. Retained history stays in the
native stream. Concrete repository adapters merge bounded pages/exact reads;
they never materialize a whole business database or inline every delta in SQL.
"""

import json
import sqlite3
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import func, select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.repositories.unification_history_repository import canonical, checksum, global_session


def blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="history_view_" + reason)


class HistoryFactView:
    def __init__(self):
        self.directory = TemporaryDirectory(prefix="f118-after-")
        self.path = Path(self.directory.name) / "delta.sqlite"
        self.database = sqlite3.connect(self.path)
        self.path.chmod(0o600)
        self.database.execute("PRAGMA cache_size=-4096")
        self.database.execute("PRAGMA temp_store=FILE")
        self.database.execute(
            "CREATE TABLE delta (family TEXT, identity TEXT, numeric_key INTEGER, text_key TEXT, "
            "tenant INTEGER, before_row TEXT, after_row TEXT, PRIMARY KEY(family, identity))"
        )
        self.database.execute("CREATE INDEX delta_owner ON delta(family,tenant,numeric_key,text_key)")
        self.database.execute(
            "CREATE TABLE member_delta (identity TEXT PRIMARY KEY, business_id TEXT, deleted INTEGER)"
        )
        self.database.execute("CREATE INDEX member_parent ON member_delta(business_id)")
        self.database.execute(
            "CREATE TABLE file_count_delta (identity TEXT PRIMARY KEY, before_parent INTEGER, "
            "before_tenant INTEGER, after_parent INTEGER, after_tenant INTEGER)"
        )
        self.database.execute("CREATE INDEX file_before_parent ON file_count_delta(before_tenant,before_parent)")
        self.database.execute("CREATE INDEX file_after_parent ON file_count_delta(after_tenant,after_parent)")
        self.graph_writes, self.graph_deletes = set(), set()
        self.logical_ids, self._next_ids = {}, {}
        self.projection_plans = []
        self.affected = defaultdict(set)
        self._prepared = False
        self._changed_ids_cache = {}
        self.closed = False

    def close(self):
        if not self.closed:
            self.closed = True
            self.database.close()
            self.directory.cleanup()

    def replace(self, family, before, after):
        if self.closed or (before is None and after is None):
            blocked("invalid_delta")
        identity = (before or after)["id"]
        if before is not None and after is not None and before["id"] != after["id"]:
            blocked("identity_changed")
        key = json.dumps(identity)
        old = self.database.execute(
            "SELECT before_row FROM delta WHERE family=? AND identity=?", (family, key)
        ).fetchone()
        original = old[0] if old is not None else json.dumps(canonical(before), sort_keys=True)
        payload = json.dumps(canonical(after), sort_keys=True)
        self.database.execute(
            "INSERT OR REPLACE INTO delta VALUES(?,?,?,?,?,?,?)",
            (
                family,
                key,
                identity if type(identity) is int else None,
                identity if type(identity) is str else None,
                (after or before).get("tenant_id"),
                original,
                payload,
            ),
        )
        self.affected[family].add(identity)
        self._changed_ids_cache.pop(family, None)
        if family == "knowledgefile":
            original_row = json.loads(original)
            self.database.execute(
                "INSERT OR REPLACE INTO file_count_delta VALUES(?,?,?,?,?)",
                (
                    key,
                    (original_row or {}).get("knowledge_id"),
                    (original_row or {}).get("tenant_id"),
                    (after or {}).get("knowledge_id"),
                    (after or {}).get("tenant_id"),
                ),
            )
        if family == "space_channel_member":
            if before is None or after is not None:
                blocked("unsupported_member_mutation")
            if before.get("business_type") == "space":
                self.database.execute("INSERT OR REPLACE INTO member_delta VALUES(?,?,1)", (key, before["business_id"]))

    def member_deletion_counts(self, business_ids):
        if type(business_ids) is not tuple or len(business_ids) > 200:
            blocked("member_count_batch_invalid")
        if not business_ids:
            return {}
        placeholders = ",".join("?" for _ in business_ids)
        return dict(
            self.database.execute(
                f"SELECT business_id,SUM(deleted) FROM member_delta WHERE business_id IN ({placeholders}) GROUP BY business_id",
                business_ids,
            )
        )

    def file_count_changes(self, resource_ids, *, tenant):
        if type(resource_ids) is not tuple or len(resource_ids) > 200:
            blocked("file_count_batch_invalid")
        if not resource_ids:
            return {}
        placeholders = ",".join("?" for _ in resource_ids)
        result = defaultdict(int)
        for side, sign in (("before", -1), ("after", 1)):
            for ident, count in self.database.execute(
                f"SELECT {side}_parent,COUNT(*) FROM file_count_delta WHERE {side}_tenant=? "
                f"AND {side}_parent IN ({placeholders}) GROUP BY {side}_parent",
                (tenant, *resource_ids),
            ):
                result[ident] += sign * count
        return dict(result)

    def changed_ids(self, family):
        if family not in self._changed_ids_cache:
            self._changed_ids_cache[family] = frozenset(
                json.loads(row[0])
                for row in self.database.execute("SELECT identity FROM delta WHERE family=?", (family,))
            )
        return self._changed_ids_cache[family]

    def states(self, family, identities):
        result = {}
        identities = tuple(identities)
        for offset in range(0, len(identities), 200):
            batch = [json.dumps(value) for value in identities[offset : offset + 200]]
            if not batch:
                continue
            placeholders = ",".join("?" for _ in batch)
            for identity, before, after in self.database.execute(
                f"SELECT identity,before_row,after_row FROM delta WHERE family=? AND identity IN ({placeholders})",
                (family, *batch),
            ):
                result[json.loads(identity)] = (json.loads(before), json.loads(after))
        return result

    async def exact_rows(self, session, model, identities, *, tenant):
        """Read one bounded identity set and apply the complete declared delta."""
        identities = tuple(identities)
        if len(identities) > 200 or len(set(identities)) != len(identities):
            blocked("exact_batch_invalid")
        if not identities:
            return ()
        table = model.__table__
        with session.no_autoflush, bypass_tenant_filter():
            native = tuple((await session.execute(select(*table.c).where(table.c.id.in_(identities)))).mappings())
        result = {row["id"]: dict(row) for row in native}
        for ident, (_before, after) in self.states(table.name, identities).items():
            if after is None:
                result.pop(ident, None)
            else:
                result[ident] = after
        if any(row.get("tenant_id") != tenant for row in result.values()):
            blocked("exact_owner_changed")
        return tuple(result[ident] for ident in identities if ident in result)

    def rows(self, family, *, tenant=None):
        query, args = "SELECT before_row,after_row FROM delta WHERE family=?", [family]
        if tenant is not None:
            query += " AND tenant=?"
            args.append(tenant)
        query += " ORDER BY numeric_key,text_key"
        for before, after in self.database.execute(query, args):
            yield json.loads(before), json.loads(after)

    def overlay(self, family, rows):
        states = self.states(family, (row["id"] for row in rows))
        return tuple(
            states[row["id"]][1] if row["id"] in states else row
            for row in rows
            if row["id"] not in states or states[row["id"]][1] is not None
        )

    def project_rows(self, family, rows):
        states = self.states(family, (row["id"] for row in rows))
        result = []
        for row in rows:
            if row["id"] not in states:
                result.append(row)
            elif states[row["id"]][1] is not None:
                after = states[row["id"]][1]
                result.append({key: after.get(key, value) for key, value in row.items()})
        return tuple(result)

    def project_resource_joins(self, row_type, rows):
        if row_type.__name__ != "VersionRow":
            return rows
        states = self.states("knowledgefile", (row["knowledge_file_id"] for row in rows))
        result = []
        for row in rows:
            if row["knowledge_file_id"] in states:
                after = states[row["knowledge_file_id"]][1]
                row = {
                    **row,
                    "file_knowledge_id": after["knowledge_id"] if after else None,
                    "file_tenant_id": after["tenant_id"] if after else None,
                    "file_type": after["file_type"] if after else None,
                }
            result.append(row)
        return tuple(result)

    def apply_tuples(self, rows, *, object=None):
        keys = {(row["user"], row["relation"], row["object"]) for row in rows}
        keys.difference_update(self.graph_deletes)
        keys.update(key for key in self.graph_writes if object is None or key[2] == object)
        return tuple(
            {"user": user, "relation": relation, "object": obj}
            for user, relation, obj in sorted(keys)
            if object is None or obj == object
        )

    async def exact_source_mappings(self, session, *, model, statement, tenant, aliases=None):
        """Finite <=200 SourceKey projection; apply AFTER before Owner checks."""
        aliases = aliases or {}
        with bypass_tenant_filter():
            raw = tuple((await session.execute(statement)).mappings())
        states = self.states(model.__tablename__, (row["id"] for row in raw))
        result = []
        for row in raw:
            if row["id"] not in states:
                values = dict(row)
            else:
                after = states[row["id"]][1]
                if after is None:
                    continue
                values = dict(row)
                for key in values:
                    source = aliases.get(key, key)
                    if source in after:
                        values[key] = typed_values(model, {source: after[source]})[source]
            if values.get("tenant_id", tenant) != tenant:
                blocked("source_wrong_tenant")
            result.append(values)
        return tuple(result)

    async def page_mappings(self, session, *, model, statement, after, limit, read, tenant, aliases=None):
        """Merge one explicitly registered keyset query, never rewrite SQL.

        Only the native query builder supplies its projection/joins. Changed
        rows are loaded by exact PK once per call (<=200 bind values), while
        ordinary pages retain their native predicates and bounded cursor.
        Historical predicates can change only owner/level/model/state fields;
        these repositories explicitly recheck owner and their native checks.
        """
        family = model.__tablename__
        aliases = aliases or {}
        changed = self.changed_ids(family)
        if not changed:
            query = statement.where(model.id > after) if after is not None else statement
            return await read(session, query.order_by(model.id).limit(limit))
        # At most the earliest `limit` changed AFTER identities can belong to
        # the merged output. Seek the indexed private delta instead of loading
        # every dirty closure again for each native page.
        key = "text_key" if type(after) is str else "numeric_key"
        if after is None:
            sample = self.database.execute("SELECT numeric_key FROM delta WHERE family=? LIMIT 1", (family,)).fetchone()
            key = "text_key" if sample and sample[0] is None else "numeric_key"
        condition, parameters = "", [family, tenant]
        if after is not None:
            condition = f" AND {key}>?"
            parameters.append(after)
        parameters.append(limit)
        after_rows = [
            (json.loads(before), json.loads(row))
            for before, row in self.database.execute(
                f"SELECT before_row,after_row FROM delta WHERE family=? AND tenant=? AND after_row!='null'"
                f"{condition} ORDER BY {key} LIMIT ?",
                parameters,
            )
        ]
        result = {}
        existing = [row["id"] for before, row in after_rows if before is not None]
        for offset in range(0, len(existing), 200):
            with bypass_tenant_filter():
                # The statement is a concrete owner projection, not arbitrary
                # SQL supplied by an operator. Exact global PK reads preserve
                # moved-owner rows and foreign-parent diagnostics.
                rows = tuple(
                    (await session.execute(statement.where(model.id.in_(existing[offset : offset + 200])))).mappings()
                )
            states = self.states(family, (row["id"] for row in rows))
            for raw in rows:
                projected = states[raw["id"]][1]
                values = dict(raw)
                for key in values:
                    source = aliases.get(key, key)
                    if source in projected:
                        values[key] = typed_values(model, {source: projected[source]})[source]
                if values.get("tenant_id", tenant) == tenant:
                    result[raw["id"]] = values
        for before, row in after_rows:
            if before is None:
                result[row["id"]] = typed_values(model, row)
        native_after = after
        while True:
            query = statement.where(model.id > native_after) if native_after is not None else statement
            page = await read(session, query.order_by(model.id).limit(200))
            for row in page:
                if row["id"] not in changed:
                    result[row["id"]] = row
            ordered = sorted(result)
            if len(page) < 200 or (len(ordered) >= limit and page[-1]["id"] >= ordered[limit - 1]):
                return tuple(result[key] for key in ordered[:limit])
            native_after = page[-1]["id"]

    def graph(self, deltas):
        from bisheng.permission.application.migration_history import terminal_graph_effect

        writes, deletes = terminal_graph_effect(deltas)
        self.graph_writes.difference_update(deletes)
        self.graph_deletes.difference_update(writes)
        self.graph_writes.update(writes)
        self.graph_deletes.update(deletes)

    def validate_file_after(self, roots):
        problems = []
        for _before, row in self.rows("knowledgefile"):
            if row is None:
                continue
            parent = roots.get(row["knowledge_id"])
            if parent is None or parent["tenant_id"] != row["tenant_id"]:
                problems.append({"table": "knowledgefile", "id": row["id"], "reason": "file_parent_invalid"})
        return problems

    async def prepare(self, session):
        """Validate every dirty AFTER and complete inverse FK closures once.

        Unchanged global predicates remain native SQL. Their dirty anchors are
        excluded only after this complete after pass has succeeded; absence
        from the original violation list never counts as validation.
        """
        if self._prepared:
            return
        from bisheng.database.models.flow import Flow
        from bisheng.database.models.flow_version import FlowVersion
        from bisheng.database.models.tag import Tag, TagLink
        from bisheng.database.models.tenant import Tenant
        from bisheng.knowledge.domain.models.knowledge import Knowledge
        from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
        from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

        async def exact(model, ids):
            found = {}
            ids = tuple(sorted(set(ids)))
            table = model.__table__
            for offset in range(0, len(ids), 200):
                with bypass_tenant_filter():
                    rows = tuple(
                        (
                            await session.execute(select(*table.c).where(table.c.id.in_(ids[offset : offset + 200])))
                        ).mappings()
                    )
                found.update((row["id"], row) for row in self.overlay(table.name, rows))
            for ident, (_before, after) in self.states(table.name, ids).items():
                if after is not None:
                    found[ident] = after
                else:
                    found.pop(ident, None)
            return found

        async def related(model, column, ids):
            ids = tuple(sorted(set(ids)))
            table = model.__table__
            found = {}
            for offset in range(0, len(ids), 200):
                after = None
                while True:
                    query = select(*table.c).where(column.in_(ids[offset : offset + 200]))
                    if after is not None:
                        query = query.where(table.c.id > after)
                    with bypass_tenant_filter():
                        page = tuple((await session.execute(query.order_by(table.c.id).limit(200))).mappings())
                    self.affected[table.name].update(row["id"] for row in page)
                    found.update((row["id"], row) for row in self.overlay(table.name, page))
                    if len(page) < 200:
                        break
                    after = page[-1]["id"]
            return found

        files = await exact(KnowledgeFile, self.affected["knowledgefile"])
        docs = await exact(KnowledgeDocument, self.affected["knowledge_document"])
        versions = await exact(KnowledgeDocumentVersion, self.affected["knowledge_document_version"])
        versions.update(
            await related(
                KnowledgeDocumentVersion, KnowledgeDocumentVersion.knowledge_file_id, self.affected["knowledgefile"]
            )
        )
        versions.update(
            await related(
                KnowledgeDocumentVersion, KnowledgeDocumentVersion.document_id, self.affected["knowledge_document"]
            )
        )
        docs.update(
            await related(
                KnowledgeDocument, KnowledgeDocument.primary_version_id, self.affected["knowledge_document_version"]
            )
        )
        docs.update(await exact(KnowledgeDocument, (row["document_id"] for row in versions.values())))
        files.update(await exact(KnowledgeFile, (row["knowledge_file_id"] for row in versions.values())))
        roots = await exact(
            Knowledge, {row["knowledge_id"] for row in (*files.values(), *docs.values())} | self.affected["knowledge"]
        )
        tenants = await exact(Tenant, (row["tenant_id"] for row in roots.values()))
        for row in roots.values():
            if row["tenant_id"] not in tenants:
                blocked("dirty_resource_tenant_invalid")
        if self.validate_file_after(roots):
            blocked("dirty_file_parent_invalid")
        for row in docs.values():
            if row["knowledge_id"] not in roots:
                blocked("dirty_document_parent_invalid")
        for row in versions.values():
            doc, file = docs.get(row["document_id"]), files.get(row["knowledge_file_id"])
            root = roots.get(doc["knowledge_id"]) if doc else None
            if (
                not doc
                or not file
                or not root
                or file["file_type"] != 1
                or file["knowledge_id"] != doc["knowledge_id"]
                or file["tenant_id"] != root["tenant_id"]
            ):
                blocked("dirty_version_parent_invalid")
        pointer_ids = {row["primary_version_id"] for row in docs.values() if row["primary_version_id"] is not None}
        pointers = await exact(KnowledgeDocumentVersion, pointer_ids)
        for row in docs.values():
            ident = row["primary_version_id"]
            if ident is not None and (ident not in pointers or pointers[ident]["document_id"] != row["id"]):
                blocked("dirty_primary_pointer_invalid")
        links = await exact(TagLink, self.affected["taglink"])
        links.update(await related(TagLink, TagLink.tag_id, self.affected["tag"]))
        links.update(
            await related(TagLink, TagLink.resource_id, (str(ident) for ident in self.affected["knowledgefile"]))
        )
        tags = await exact(Tag, {row["tag_id"] for row in links.values()} | self.affected["tag"])
        target_ids = {
            int(row["resource_id"])
            for row in links.values()
            if row["resource_type"] in (8, 9)
            and str(row["resource_id"]).isascii()
            and str(row["resource_id"]).isdecimal()
        }
        targets = await exact(KnowledgeFile, target_ids)
        for row in links.values():
            tag = tags.get(row["tag_id"])
            if not tag or tag["tenant_id"] != row["tenant_id"]:
                blocked("dirty_tag_parent_invalid")
            if row["resource_type"] in (8, 9):
                ident = str(row["resource_id"])
                file = targets.get(int(ident)) if ident.isascii() and ident.isdecimal() else None
                if file is None or file["tenant_id"] != row["tenant_id"]:
                    blocked("dirty_tag_file_invalid")
        flows = await exact(FlowVersion, self.affected["flowversion"])
        parents = await exact(Flow, (row["flow_id"] for row in flows.values()))
        for row in flows.values():
            parent = parents.get(row["flow_id"])
            if parent is None or parent["flow_type"] != 10 or row["tenant_id"] != parent["tenant_id"]:
                blocked("dirty_workflow_parent_invalid")
        owners = {
            row["tenant_id"]
            for row in (*roots.values(), *files.values(), *tags.values(), *links.values(), *flows.values())
        }
        actual_owners = await exact(Tenant, owners)
        if set(actual_owners) != owners:
            blocked("dirty_business_tenant_invalid")
        self._prepared = True

    async def validate_permission_global(self, session, *, retained_tenant_ids=()):
        from bisheng.common.errcode.permission import PermissionMigrationBlockedError
        from bisheng.database.models.tenant import Tenant
        from bisheng.permission.domain.models import (
            PermissionGrant,
            PermissionGrantAssignee,
            PermissionVisibleSourceProjection,
            ResourcePermissionMode,
        )

        tenant = Tenant.__table__.alias("history_actual_tenant")
        models = (ResourcePermissionMode, PermissionGrant, PermissionGrantAssignee, PermissionVisibleSourceProjection)
        removed_scopes = [
            (before["tenant_id"], before["resource_type"], before["resource_id"])
            for before, after in self.rows("resource_permission_mode")
            if before is not None and after is None
        ]
        if removed_scopes:
            from sqlalchemy import and_, or_

            for model in (PermissionGrant, PermissionVisibleSourceProjection):
                table = model.__table__
                for offset in range(0, len(removed_scopes), 50):
                    condition = or_(
                        *(
                            and_(
                                table.c.tenant_id == owner, table.c.resource_type == kind, table.c.resource_id == ident
                            )
                            for owner, kind, ident in removed_scopes[offset : offset + 50]
                        )
                    )
                    cursor = None
                    while True:
                        query = select(*table.c).where(condition)
                        if cursor is not None:
                            query = query.where(table.c.id > cursor)
                        with bypass_tenant_filter():
                            page = tuple((await session.execute(query.order_by(table.c.id).limit(200))).mappings())
                        if self.overlay(table.name, page):
                            blocked("dirty_removed_scope_has_remaining_mirror")
                        if len(page) < 200:
                            break
                        cursor = page[-1]["id"]
        # A removed grant must not hide a newly appearing child behind the
        # original SQL JOIN. Close inverse edges before excluding dirty anchors.
        grant_ids = tuple(sorted(self.changed_ids("permission_grant")))
        closure_children = {}
        table = PermissionGrantAssignee.__table__
        for offset in range(0, len(grant_ids), 200):
            cursor = None
            while True:
                query = select(*table.c).where(table.c.grant_id.in_(grant_ids[offset : offset + 200]))
                if cursor is not None:
                    query = query.where(table.c.id > cursor)
                with bypass_tenant_filter():
                    page = tuple((await session.execute(query.order_by(table.c.id).limit(200))).mappings())
                self.affected[table.name].update(row["id"] for row in page)
                closure_children.update((row["id"], row) for row in self.overlay(table.name, page))
                if len(page) < 200:
                    break
                cursor = page[-1]["id"]
        owners = {
            row["tenant_id"]
            for model in models
            for _before, row in self.rows(model.__tablename__)
            if row is not None and row["tenant_id"] not in retained_tenant_ids
        }
        actual_owners = set()
        ordered_owners = tuple(sorted(owners))
        for offset in range(0, len(ordered_owners), 200):
            with bypass_tenant_filter():
                actual_owners.update(
                    (
                        await session.execute(
                            select(Tenant.id).where(Tenant.id.in_(ordered_owners[offset : offset + 200]))
                        )
                    ).scalars()
                )
        if owners != actual_owners:
            blocked("dirty_permission_tenant_invalid")
        for model in models:
            table = model.__table__.alias("history_original_" + model.__tablename__)
            condition = table.c.tenant_id.is_(None) | tenant.c.id.is_(None)
            for offset in range(0, len(retained_tenant_ids), 200):
                condition &= table.c.tenant_id.is_(None) | table.c.tenant_id.not_in(
                    retained_tenant_ids[offset : offset + 200]
                )
            query = select(table.c.id).outerjoin(tenant, tenant.c.id == table.c.tenant_id).where(condition)
            query = self.exclude_affected_probe(query)
            with bypass_tenant_filter():
                if (await session.execute(query.limit(1))).first() is not None:
                    raise PermissionMigrationBlockedError(reason="f118_snapshot_global_original_orphan")
        child, parent = (
            PermissionGrantAssignee.__table__.alias("history_original_assignee"),
            PermissionGrant.__table__.alias("history_original_grant"),
        )
        query = (
            select(child.c.id)
            .outerjoin(parent, parent.c.id == child.c.grant_id)
            .where(parent.c.id.is_(None) | (child.c.tenant_id != parent.c.tenant_id))
        )
        with bypass_tenant_filter():
            if (await session.execute(self.exclude_affected_probe(query).limit(1))).first() is not None:
                raise PermissionMigrationBlockedError(reason="f118_snapshot_global_original_orphan")
        changed = {row["id"]: row for _before, row in self.rows("permission_grant_assignee") if row is not None}
        changed.update(closure_children)
        changed = list(changed.values())
        ids = tuple(sorted({row["grant_id"] for row in changed}))
        grants = {}
        for offset in range(0, len(ids), 200):
            table = PermissionGrant.__table__
            with bypass_tenant_filter():
                rows = tuple(
                    (
                        await session.execute(select(*table.c).where(table.c.id.in_(ids[offset : offset + 200])))
                    ).mappings()
                )
            grants.update((row["id"], row) for row in self.overlay(table.name, rows))
        for row in changed:
            if row["grant_id"] not in grants or grants[row["grant_id"]]["tenant_id"] != row["tenant_id"]:
                blocked("dirty_assignee_parent_invalid")

    def exclude_affected_probe(self, statement):
        column = next(iter(statement.selected_columns))
        table = getattr(column, "table", None)
        table = getattr(table, "original", table)
        family = getattr(table, "name", None)
        # Aggregate creation-key probes are unchanged by the explicit history
        # field allowlist, so they always execute on the complete native group.
        ids = tuple(sorted(self.affected.get(family, ())))
        for offset in range(0, len(ids), 200):
            statement = statement.where(column.not_in(ids[offset : offset + 200]))
        return statement

    async def allocate(self, session, model, logical):
        family = model.__tablename__
        key = (family, logical)
        if key not in self.logical_ids:
            if family not in self._next_ids:
                with bypass_tenant_filter():
                    actual = (await session.execute(select(func.max(model.id)))).scalar_one()
                self._next_ids[family] = actual or 0
            self._next_ids[family] += 1
            if self._next_ids[family] >= 2**63:
                blocked("preview_identity_capacity")
            self.logical_ids[key] = self._next_ids[family]
        return self.logical_ids[key]

    def manifest(self):
        from dataclasses import fields

        from bisheng.permission.domain.schemas import VisibleSourceProjectionDTO
        from bisheng.permission.migration.f118_plan import (
            PermissionAssigneeBaseline,
            PermissionGrantBaseline,
            ResourceModeBaseline,
        )

        closed = {
            "resource_permission_mode": {field.name for field in fields(ResourceModeBaseline)},
            "permission_grant": {field.name for field in fields(PermissionGrantBaseline)},
            "permission_grant_assignee": {field.name for field in fields(PermissionAssigneeBaseline)},
            "permission_visible_source_projection": {"id", *VisibleSourceProjectionDTO.model_fields},
            "permission_projection_operation": {
                "id",
                "tenant_id",
                "idempotency_key",
                "request_checksum",
                "operation_type",
                "scope_type",
                "scope_key",
                "expected_version",
                "target_version",
                "store_id",
                "model_id",
                "before_checksum",
                "after_checksum",
                "operator_id",
                "status",
            },
            "permission_projection_tuple": {
                "id",
                "tenant_id",
                "operation_id",
                "phase",
                "sequence",
                "action",
                "fga_user",
                "relation",
                "fga_object",
                "tuple_fingerprint",
                "inverse_action",
            },
        }
        result = []
        for family, identity, before, after in self.database.execute(
            "SELECT family,identity,before_row,after_row FROM delta ORDER BY family,numeric_key,text_key"
        ):
            original, expected = json.loads(before), json.loads(after)
            item = {
                "table": family,
                "id": json.loads(identity),
                "before": checksum(original),
                "after": checksum(expected),
                "ignore_fields": [],
            }
            if family in closed:
                item["after_fact"] = {key: expected[key] for key in closed[family]} if expected is not None else None
                item["before_scope"] = {
                    key: original[key]
                    for key in ("tenant_id", "resource_type", "resource_id")
                    if original is not None and key in original
                }
                item["after"] = checksum(item["after_fact"])
            elif family in {"knowledgefile", "knowledge_document"}:
                # Historical level repair explicitly preserves update_time.
                # Old interrupted operations may already have advanced this
                # audit field, which was never part of their level fence.
                item["ignore_fields"] = ["update_time"] + (["tenant_id"] if family == "knowledge_document" else [])
                item["after"] = (
                    checksum({key: value for key, value in expected.items() if key not in item["ignore_fields"]})
                    if expected
                    else checksum(None)
                )
            result.append(item)
        return {
            "schema": 1,
            "rows": result,
            "graph_writes": sorted(self.graph_writes),
            "graph_deletes": sorted(self.graph_deletes),
            "logical_ids": [
                {"table": key[0], "identity": key[1], "preview_id": value}
                for key, value in sorted(self.logical_ids.items())
            ],
            "projection_plans": self.projection_plans,
        }


def typed_values(model, values):
    """Restore native scalar types after the private JSON scratch roundtrip."""
    from sqlalchemy import DateTime

    result = dict(values)
    for column in model.__table__.c:
        if isinstance(column.type, DateTime) and isinstance(result.get(column.name), str):
            result[column.name] = datetime.fromisoformat(result[column.name])
    return result


async def build_history_view(plan, *, sessions, client, operator_id=0, logical_ids=None):
    from bisheng.knowledge.domain.repositories import unification_history_delete_closure as closures
    from bisheng.knowledge.domain.repositories.unification_history_repository import history_plan_identity, target_for
    from bisheng.permission.application.migration_history import (
        build_create_plan,
        build_delete_plan,
        build_projection_operation,
        finalization_effect,
        projection_request_checksum,
    )
    from bisheng.permission.domain.models import (
        PermissionProjectionOperation,
        PermissionProjectionTuple,
        ResourcePermissionMode,
    )
    from bisheng.permission.domain.services.projection_plan import ProjectionTupleDelta
    from bisheng.permission.domain.services.projection_service import restore_projection_plan

    view = HistoryFactView()
    try:
        view.logical_ids.update({(row["table"], row["identity"]): row["preview_id"] for row in logical_ids or ()})
        identity = history_plan_identity(plan)[:32]
        for item in plan.get("business", {}).get("updates", ()):
            view.replace(item["table"], item["before"], {**item["before"], **item["values"]})
        for item in plan.get("business", {}).get("deletes", ()):
            if set(item["before"]) - {"id", "file_type"}:
                view.replace(item["table"], item["before"], None)
        for item in plan.get("levels", ()):
            before = item["before"]
            after = view.states(item["table"], (before["id"],)).get(before["id"], (None, before))[1]
            if after is None:
                blocked("level_after_deleted")
            view.replace(item["table"], before, {**after, "level": item["after_level"]})

        async with global_session(sessions) as session:

            async def effect(projection, mirrors, *, original=None):
                op_id = (
                    original.id
                    if original is not None
                    else await view.allocate(session, PermissionProjectionOperation, projection.idempotency_key)
                )
                if original is None:
                    from dataclasses import asdict

                    view.projection_plans.append({"preview_operation_id": op_id, "plan": asdict(projection)})
                    operation, tuples = build_projection_operation(
                        projection, request_checksum=projection_request_checksum(projection)
                    )
                    operation.id, operation.status = op_id, "FINALIZED"
                    view.replace(operation.__tablename__, None, operation.model_dump())
                    for row in tuples:
                        row.id = await view.allocate(
                            session,
                            PermissionProjectionTuple,
                            f"{projection.idempotency_key}:{row.phase}:{row.sequence}",
                        )
                        row.operation_id = op_id
                        view.replace(row.__tablename__, None, row.model_dump())
                else:
                    view.replace(
                        original.__tablename__, original.model_dump(), {**original.model_dump(), "status": "FINALIZED"}
                    )
                current = {family: list(view.overlay(family, rows)) for family, rows in mirrors.items()}
                mode = current["resource_permission_mode"][0]
                mode = {**mode, "operation_id": op_id, "projection_state": "PROJECTING"}
                current["resource_permission_mode"] = [mode]
                after = finalization_effect(projection, op_id, current)
                for family, rows in after.items():
                    previous = {row["id"]: row for row in mirrors.get(family, ())}
                    for row in rows:
                        view.replace(family, previous.get(row["id"]), row)
                view.graph(projection.deltas)
                return op_id, after

            def empty(mode):
                return {
                    "resource_permission_mode": [mode],
                    "permission_grant": [],
                    "permission_grant_assignee": [],
                    "permission_visible_source_projection": [],
                }

            for item in plan.get("initializations", ()):
                row = item["file"]
                target = target_for(
                    {
                        "tenant_id": row["tenant_id"],
                        "resource_type": "knowledge_file",
                        "resource_id": str(row["id"]),
                        "version": 0,
                        "parent_type": "knowledge_library",
                        "parent_id": str(row["knowledge_id"]),
                    }
                )
                projection = build_create_plan(
                    target,
                    store_id=plan["pin"]["store_id"],
                    model_id=plan["pin"]["model_id"],
                    operator_id=operator_id,
                    idempotency_key=f"history-initialize:{identity}:{row['id']}",
                    protected_deltas=(),
                    permission_mode="INHERIT",
                )
                mode = ResourcePermissionMode(
                    id=await view.allocate(session, ResourcePermissionMode, projection.scope_key),
                    tenant_id=row["tenant_id"],
                    resource_type="knowledge_file",
                    resource_id=str(row["id"]),
                    mode="INHERIT",
                    parent_type=target.parent_type,
                    parent_id=target.parent_id,
                    version=0,
                    projection_state="PENDING",
                ).model_dump()
                _, after = await effect(projection, empty(mode))
                # It was absent in SQL, even though reservation/finalize have
                # a synthetic mode as their internal before.
                state = after["resource_permission_mode"][0]
                view.database.execute(
                    "DELETE FROM delta WHERE family=? AND identity=?",
                    ("resource_permission_mode", json.dumps(mode["id"])),
                )
                view.replace("resource_permission_mode", None, state)

            for item in (*plan.get("recoveries", ()), *plan.get("builtin_finalizations", ())):
                original = (
                    await session.execute(
                        select(PermissionProjectionOperation).where(
                            PermissionProjectionOperation.id == item["ledger"]["id"]
                        )
                    )
                ).scalar_one()
                tuples = (
                    (
                        await session.execute(
                            select(PermissionProjectionTuple)
                            .where(PermissionProjectionTuple.operation_id == original.id)
                            .order_by(PermissionProjectionTuple.sequence)
                        )
                    )
                    .scalars()
                    .all()
                )
                projection = restore_projection_plan(original, tuples)
                await effect(projection, item["sql"], original=original)
            for item in plan.get("delete_closures", ()):
                projection = closures.projection_plan(plan, item, identity=identity, operator_id=operator_id)
                mirrors = {"resource_permission_mode": [item["mode"]], **item["mirrors"]}
                await effect(projection, mirrors)
            for item in plan.get("empty_root_initializations", ()):
                row = item["business"]
                target = target_for(
                    {
                        "tenant_id": row["tenant_id"],
                        "resource_type": "knowledge_library",
                        "resource_id": str(row["id"]),
                        "version": 0,
                        "parent_type": None,
                        "parent_id": None,
                    }
                )
                projection = build_delete_plan(
                    target,
                    store_id=plan["pin"]["store_id"],
                    model_id=plan["pin"]["model_id"],
                    operator_id=operator_id,
                    idempotency_key=f"history-empty-root-closed:{identity}:{row['id']}",
                )
                mode = ResourcePermissionMode(
                    id=await view.allocate(session, ResourcePermissionMode, projection.scope_key),
                    tenant_id=row["tenant_id"],
                    resource_type="knowledge_library",
                    resource_id=str(row["id"]),
                    mode="CUSTOM",
                    version=0,
                    projection_state="PENDING",
                ).model_dump()
                _, after = await effect(projection, empty(mode))
                view.database.execute(
                    "DELETE FROM delta WHERE family=? AND identity=?",
                    ("resource_permission_mode", json.dumps(mode["id"])),
                )
                view.replace("resource_permission_mode", None, after["resource_permission_mode"][0])
            for item in plan.get("parents", ()):
                mode = item["mode"]
                projection = build_delete_plan(
                    target_for(mode),
                    store_id=plan["pin"]["store_id"],
                    model_id=plan["pin"]["model_id"],
                    operator_id=operator_id,
                    idempotency_key=f"history-parent:{identity}:{mode['id']}",
                )
                count = len(item["deletes"])
                projection = replace(
                    projection,
                    operation_type="HISTORICAL_PARENT_REPAIR",
                    deltas=tuple(
                        ProjectionTupleDelta("STAGE" if index < count - 90 else "COMMIT", index, "DELETE", *key)
                        for index, key in enumerate(item["deletes"])
                    ),
                )
                from bisheng.knowledge.domain.repositories.unification_history_repository import mirrors as load_mirrors

                mirrors, _ = await load_mirrors(session, mode)
                mirrors["resource_permission_mode"] = [mode]
                await effect(projection, mirrors)
            for item in plan.get("purges", ()):
                mode = item["mode"]
                projection = build_delete_plan(
                    target_for(mode),
                    store_id=plan["pin"]["store_id"],
                    model_id=plan["pin"]["model_id"],
                    operator_id=operator_id,
                    idempotency_key=f"history-delete:{identity}:{mode['id']}",
                )
                original_id, after = await effect(projection, item["sql"])
                remaining = sorted(
                    {(row["user"], row["relation"], row["object"]) for row in item["tuples"]} - view.graph_deletes
                )
                if remaining:
                    start = max(0, len(remaining) - 90)
                    cleanup = replace(
                        projection,
                        operation_type="RESOURCE_DELETE_PURGE",
                        idempotency_key=f"resource-purge:{original_id}",
                        expected_version=projection.target_version,
                        target_version=projection.target_version + 1,
                        deltas=tuple(
                            ProjectionTupleDelta("STAGE" if index < start else "COMMIT", index, "DELETE", *key)
                            for index, key in enumerate(remaining)
                        ),
                    )
                    _, after = await effect(cleanup, after)
                for family, rows in after.items():
                    for row in rows:
                        view.replace(family, row, None)
        return view
    except BaseException:
        view.close()
        raise
