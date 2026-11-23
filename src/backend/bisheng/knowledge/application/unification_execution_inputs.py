"""Disposable, bounded F118 input materialization for one maintenance execution.

Remote content-addressed objects and native SQL remain authoritative. These
private files are never accepted from callers and never reused after restart.
"""

import hashlib
import io
import json
import os
import pickle
import sqlite3
from collections import OrderedDict
from pathlib import Path
from tempfile import TemporaryDirectory

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.knowledge.domain.repositories.unification_run_repository import FrozenGlobalInventoryResult
from bisheng.knowledge.domain.services.unification_fingerprints import canonical, digest


def _blocked(reason):
    raise ReferenceCoverageNotReadyError(reason="migration_execution_inputs_" + reason)


class _PlanWriter(pickle.Pickler):
    def persistent_id(self, value):
        return "catalog" if value is self.catalog else None


class _PlanReader(pickle.Unpickler):
    def persistent_load(self, value):
        if value != "catalog":
            _blocked("plan_reference")
        return self.catalog


class _Plans:
    """Read only a single row/batch from locally compiled, sealed output."""

    def __init__(self, bundle, tenant):
        self.bundle, self.tenant = bundle, tenant

    def __len__(self):
        return self.bundle.database.execute("SELECT count(*) FROM plans WHERE tenant=?", (self.tenant,)).fetchone()[0]

    def _restore(self, data, checksum):
        if hashlib.sha256(data).hexdigest() != checksum:
            _blocked("plan_cache_changed")
        reader = _PlanReader(io.BytesIO(data))
        reader.catalog = self.bundle.permission_planner.catalog_plan
        return reader.load()

    def __iter__(self):
        self.bundle.require_sealed()
        cursor = self.bundle.database.execute(
            "SELECT payload,checksum FROM plans WHERE tenant=? ORDER BY ordinal", (self.tenant,)
        )
        try:
            for data, checksum in cursor:
                yield self._restore(data, checksum)
        finally:
            cursor.close()

    def __getitem__(self, key):
        self.bundle.require_sealed()
        size = len(self)
        if isinstance(key, slice):
            start, stop, step = key.indices(size)
            if step != 1 or stop - start > 200:
                raise ValueError("compiled plan slices must contain at most 200 rows")
            rows = self.bundle.database.execute(
                "SELECT payload,checksum FROM plans WHERE tenant=? AND ordinal>=? AND ordinal<? ORDER BY ordinal",
                (self.tenant, start, stop),
            )
            return tuple(self._restore(data, checksum) for data, checksum in rows)
        if type(key) is not int:
            raise TypeError("compiled plan index must be an integer or bounded slice")
        index = key + size if key < 0 else key
        row = self.bundle.database.execute(
            "SELECT payload,checksum FROM plans WHERE tenant=? AND ordinal=?", (self.tenant, index)
        ).fetchone()
        if row is None:
            raise IndexError(key)
        return self._restore(*row)


class InventoryBundle:
    def __init__(self, execution, key, frozen):
        self.execution, self.key, self.run_id = execution, key, frozen.run_id
        self.sealed, self.permission_planner, self.page_count = False, None, 0
        self._counts = {}
        self._directory = TemporaryDirectory(prefix="inventory-", dir=execution.directory)
        path = Path(self._directory.name) / "input.sqlite"
        path.touch(mode=0o600)
        self.database = sqlite3.connect(path)
        self.database.execute(
            "CREATE TABLE pages (ordinal INTEGER PRIMARY KEY, metadata TEXT NOT NULL, checksum TEXT NOT NULL)"
        )
        self.database.execute(
            "CREATE TABLE plans (tenant INTEGER, ordinal INTEGER, payload BLOB NOT NULL, checksum TEXT NOT NULL, "
            "PRIMARY KEY(tenant,ordinal))"
        )

    def set_planner(self, planner):
        if self.sealed or (
            self.permission_planner is not None and self.permission_planner.catalog_plan != planner.catalog_plan
        ):
            _blocked("planner_changed")
        self.permission_planner = planner

    def observe_plan(self, tenant, plan):
        if self.sealed or self.permission_planner is None or plan.before.tenant_id != tenant:
            _blocked("plan_not_collecting")
        target = io.BytesIO()
        writer = _PlanWriter(target, protocol=pickle.HIGHEST_PROTOCOL)
        writer.catalog = self.permission_planner.catalog_plan
        writer.dump(plan)
        data = target.getvalue()
        ordinal = self._counts.get(tenant, 0)
        self.database.execute(
            "INSERT INTO plans VALUES (?,?,?,?)", (tenant, ordinal, data, hashlib.sha256(data).hexdigest())
        )
        self._counts[tenant] = ordinal + 1

    def append_page(self, page):
        if self.sealed:
            _blocked("sealed_append")
        metadata = {
            name: getattr(page, name)
            for name in ("kind", "section", "scope", "tenant_id", "page_index", "record_count", "descriptor")
        }
        kind = "sources" if page.section == "sources" else page.kind
        self.execution.remember((self.run_id, kind, page.descriptor["sha256"]), page.content)
        self.database.execute(
            "INSERT INTO pages VALUES (?,?,?)", (self.page_count, canonical(metadata).decode(), digest(metadata))
        )
        self.page_count += 1

    def seal(self):
        if self.permission_planner is None:
            _blocked("missing_permission_verification")
        self.database.commit()
        self.sealed = True

    def require_sealed(self):
        if not self.sealed:
            _blocked("unsealed")

    def require_planner(self, planner):
        self.require_sealed()
        if planner is not None and planner.catalog_plan != self.permission_planner.catalog_plan:
            _blocked("supplied_planner_changed")

    def plans(self, tenant):
        self.require_sealed()
        return _Plans(self, tenant)

    async def iter_pages(self, page_factory):
        self.require_sealed()
        cursor = self.database.execute("SELECT metadata,checksum FROM pages ORDER BY ordinal")
        count = 0
        try:
            for metadata, checksum in cursor:
                values = json.loads(metadata)
                if digest(values) != checksum:
                    _blocked("page_metadata_changed")
                kind = "sources" if values["section"] == "sources" else values["kind"]
                content = await self.execution.store.aload_canonical(
                    values["descriptor"], run_id=self.run_id, kind=kind
                )
                yield page_factory(**values, content=content)
                count += 1
            if count != self.page_count:
                _blocked("page_membership_changed")
        finally:
            cursor.close()

    def abort(self):
        self.execution.inventories.pop(self.key, None)
        self.close()

    def close(self):
        self.database.close()
        self._directory.cleanup()


class VerifiedExecutionInputs:
    def __init__(self, store, *, max_bytes):
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("verified input memory limit must be positive")
        self.store, self.max_bytes, self.memory_bytes = store, max_bytes, 0
        self._directory = TemporaryDirectory(prefix="f118-verified-inputs-")
        self.directory = self._directory.name
        self._memory, self.inventories = OrderedDict(), {}

    def _path(self, key):
        return Path(self.directory) / (digest(key) + ".bytes")

    def read(self, key):
        if key in self._memory:
            self._memory.move_to_end(key)
            return self._memory[key]
        path = self._path(key)
        if not path.exists():
            return None
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != key[2]:
            path.unlink()
            return None
        self._hot(key, data)
        return data

    def _hot(self, key, data):
        old = self._memory.pop(key, None)
        self.memory_bytes -= len(old) if old is not None else 0
        if len(data) > self.max_bytes:
            return
        while self._memory and self.memory_bytes + len(data) > self.max_bytes:
            _, expired = self._memory.popitem(last=False)
            self.memory_bytes -= len(expired)
        self._memory[key] = data
        self.memory_bytes += len(data)

    def remember(self, key, data):
        if hashlib.sha256(data).hexdigest() != key[2]:
            _blocked("bytes_changed")
        path = self._path(key)
        if not path.exists():
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
                output.write(data)
        self._hot(key, data)

    def inventory_key(self, frozen, *, environment, backup_ref, schema_ref):
        if (
            type(frozen) is not FrozenGlobalInventoryResult
            or type(frozen.tenant_ids) is not tuple
            or not frozen.tenant_ids
            or any(type(tenant) is not int or tenant <= 0 for tenant in frozen.tenant_ids)
            or tuple(sorted(set(frozen.tenant_ids))) != frozen.tenant_ids
        ):
            raise KnowledgeOperationPlanConflictError(reason="migration_inventory_invalid_frozen_input")
        values = {
            "run_id": frozen.run_id,
            "writer": frozen.writer_contract_version,
            "tenants": frozen.tenant_ids,
            "baseline": frozen.baseline_ref,
            "plan": frozen.plan_ref,
            "environment": environment,
            "backup_ref": backup_ref,
            "schema_ref": schema_ref,
            "protocol": "verified-inputs-v1",
        }
        key = digest(values)
        # Only execution-local typed frozen identities are retained here.
        self._frozen = getattr(self, "_frozen", {})
        self._frozen[key] = frozen
        return key

    def get_inventory(self, key):
        return self.inventories.get(key)

    def begin_inventory(self, key):
        if key in self.inventories:
            _blocked("inventory_already_collecting")
        bundle = InventoryBundle(self, key, self._frozen[key])
        self.inventories[key] = bundle
        return bundle

    def close(self):
        try:
            for bundle in tuple(self.inventories.values()):
                bundle.close()
        finally:
            self.inventories.clear()
            self._memory.clear()
            self.memory_bytes = 0
            self._directory.cleanup()
