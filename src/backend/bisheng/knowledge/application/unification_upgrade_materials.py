"""Private immutable preview materials; local files never replace the Run ledger."""

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_LIMIT = 16 * 1024 * 1024


def reject_material(reason):
    raise KnowledgeOperationPlanConflictError(reason="migration_material_" + reason)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def envelope(run_id, kind, records):
    return {"schema_version": 1, "run_id": run_id, "kind": kind, "records": records}


def descriptor(run_id, kind, content):
    digest = hashlib.sha256(content).hexdigest()
    return {"object_key": f"f118/unification/{run_id}/{kind}/{digest}.json", "sha256": digest}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            reject_material("duplicate_key")
        result[key] = value
    return result


def decode(content):
    try:
        value = json.loads(content, object_pairs_hook=_pairs)
        if canonical(value) != content:
            reject_material("noncanonical")
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise KnowledgeOperationPlanConflictError(reason="migration_material_invalid_json") from error


class UpgradeMaterials:
    def __init__(self, root, *, run_id):
        if not isinstance(run_id, str) or _NAME.fullmatch(run_id) is None:
            reject_material("invalid_run")
        self.run_id, self.root = run_id, Path(root).absolute()
        self._directory(self.root)
        self._directory(self.root / "objects")
        self._directory(self.root / "reports")
        self._directory(self.root / "private")

    @staticmethod
    def _directory(path):
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
            reject_material("unsafe_directory")

    @staticmethod
    def _read(path):
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > _LIMIT:
                    reject_material("unsafe_file")
                data = stream.read(_LIMIT + 1)
            if not data or len(data) > _LIMIT:
                reject_material("invalid_size")
            return data
        except OSError as error:
            raise KnowledgeOperationPlanConflictError(reason="migration_material_missing_or_unreadable") from error

    def _write(self, path, content, *, immutable):
        if not isinstance(content, bytes) or not content or len(content) > _LIMIT:
            reject_material("invalid_size")
        fd, temporary = tempfile.mkstemp(prefix=".f118-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if immutable:
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    if self._read(path) != content:
                        reject_material("immutable_conflict")
            else:
                os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def write_object(self, kind, value):
        content = canonical(value)
        self._validate(value, kind)
        ref = descriptor(self.run_id, kind, content)
        self._write(self.root / "objects" / (ref["sha256"] + ".json"), content, immutable=True)
        return ref

    def _validate(self, value, kind):
        if (
            type(value) is not dict
            or set(value) != {"schema_version", "run_id", "kind", "records"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["run_id"] != self.run_id
            or value["kind"] != kind
            or not isinstance(kind, str)
            or _NAME.fullmatch(kind) is None
            or type(value["records"]) is not list
        ):
            reject_material("invalid_envelope")

    def read_bytes(self, ref, *, kind):
        if type(ref) is not dict or set(ref) != {"object_key", "sha256"} or not isinstance(ref["sha256"], str):
            reject_material("invalid_descriptor")
        if _HASH.fullmatch(ref["sha256"]) is None:
            reject_material("invalid_descriptor")
        data = self._read(self.root / "objects" / (ref["sha256"] + ".json"))
        if descriptor(self.run_id, kind, data) != ref:
            reject_material("descriptor_changed")
        self._validate(decode(data), kind)
        return data

    def read_object(self, ref, *, kind):
        return decode(self.read_bytes(ref, kind=kind))

    def activate(self, flow_ref):
        flow = self.read_object(flow_ref, kind="upgrade_flow")
        records = flow["records"]
        if len(records) == 1 and records[0].get("kind") == "new_run":
            self._write(
                self.root / "flow.json", canonical({"run_id": self.run_id, "flow_ref": flow_ref}), immutable=True
            )
        elif len(records) == 1 and records[0].get("kind") == "frozen_resume":
            directory = self.root / "reconciliation" / flow_ref["sha256"]
            self._directory(directory.parent)
            self._directory(directory)
            self._write(directory / "manifest.json", canonical(flow), immutable=True)
        self._write(
            self.root / "ACTIVE.json", canonical({"run_id": self.run_id, "flow_ref": flow_ref}), immutable=False
        )

    def active(self, *, required=True):
        path = self.root / "ACTIVE.json"
        if not path.exists() and not path.is_symlink() and not required:
            return None
        value = decode(self._read(path))
        if type(value) is not dict or set(value) != {"run_id", "flow_ref"} or value["run_id"] != self.run_id:
            reject_material("active_run_changed")
        self.read_object(value["flow_ref"], kind="upgrade_flow")
        return value["flow_ref"]

    def reconciliation_candidates(self):
        root = self.root / "reconciliation"
        if not root.exists() and not root.is_symlink():
            return
        self._directory(root)
        for directory in root.iterdir():
            if _HASH.fullmatch(directory.name) is None:
                reject_material("unexpected_reconciliation")
            self._directory(directory)
            data = self._read(directory / "manifest.json")
            value = decode(data)
            self._validate(value, "upgrade_flow")
            ref = descriptor(self.run_id, "upgrade_flow", data)
            if ref["sha256"] != directory.name or len(value["records"]) != 1:
                reject_material("reconciliation_changed")
            yield ref, value["records"][0]

    def write_report(self, report):
        data = canonical(report)
        digest = hashlib.sha256(data).hexdigest()
        path = self.root / "reports" / (digest + ".json")
        self._write(path, data, immutable=True)
        return str(path)

    async def upload(self, store, ref, *, kind):
        uploaded = await store.aput_canonical(run_id=self.run_id, kind=kind, content=self.read_bytes(ref, kind=kind))
        if uploaded != ref:
            reject_material("remote_identity_changed")
        return uploaded

    def local_store(self, original):
        from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore

        store = UnificationArtifactStore(_LocalMaterialStorage(self, original))
        # Local preview pages and remote immutable inputs share one command's
        # bounded hot/disk cache, rather than allocating 64 MiB per stage.
        store.verified_inputs = original.verified_inputs
        return store

    async def upload_tree(self, store, flow_ref):
        """Publish just the selected closed material graph, dependencies first."""
        return await self._walk_tree(store, flow_ref, publish=True)

    async def validate_tree(self, store, flow_ref):
        """Check actual local bytes and all required descendants without writes."""
        return await self._walk_tree(store, flow_ref, publish=False)

    async def _walk_tree(self, store, flow_ref, *, publish):
        seen = set()

        def references(value):
            if isinstance(value, dict):
                if set(value) == {"object_key", "sha256"}:
                    yield value
                else:
                    for key, item in value.items():
                        if key not in {"backup_ref", "schema_ref"}:
                            yield from references(item)
            elif isinstance(value, list):
                for item in value:
                    yield from references(item)

        async def visit(ref, depth=0):
            if depth > 64:
                reject_material("graph_too_deep")
            key = ref.get("object_key")
            if key in seen:
                return
            seen.add(key)
            parts = key.split("/") if isinstance(key, str) else []
            # Historical backup/schema locators remain opaque identity fields;
            # their contents are not migration input or a backup attestation.
            if len(parts) != 5 or parts[:3] != ["f118", "unification", self.run_id]:
                return
            kind = parts[3]
            path = self.root / "objects" / (ref["sha256"] + ".json")
            if path.exists() or path.is_symlink():
                content = self.read_bytes(ref, kind=kind)
                for child in references(decode(content)["records"]):
                    await visit(child, depth + 1)
                if publish:
                    await self.upload(store, ref, kind=kind)
            else:
                content = await store.aload_canonical(ref, run_id=self.run_id, kind=kind)
                for child in references(decode(content)["records"]):
                    await visit(child, depth + 1)

        await visit(flow_ref)
        return len(seen)


class _LocalMaterialStorage:
    def __init__(self, materials, original):
        self.materials, self.original = materials, original
        self.bucket, self.tmp_bucket = original.bucket, None

    def _identity(self, object_name):
        parts = object_name.split("/")
        if len(parts) != 5 or parts[:3] != ["f118", "unification", self.materials.run_id]:
            reject_material("invalid_object_key")
        kind, filename = parts[3:]
        if not filename.endswith(".json") or _HASH.fullmatch(filename[:-5]) is None:
            reject_material("invalid_object_key")
        return kind, {"object_key": object_name, "sha256": filename[:-5]}

    async def object_exists(self, *, bucket_name, object_name):
        _, ref = self._identity(object_name)
        return (self.materials.root / "objects" / (ref["sha256"] + ".json")).exists()

    async def put_object(self, *, bucket_name, object_name, file, content_type):
        kind, ref = self._identity(object_name)
        if self.materials.write_object(kind, decode(file)) != ref:
            reject_material("descriptor_changed")

    async def get_object(self, *, bucket_name, object_name):
        kind, ref = self._identity(object_name)
        path = self.materials.root / "objects" / (ref["sha256"] + ".json")
        if path.exists() or path.is_symlink():
            return self.materials.read_bytes(ref, kind=kind)
        # Frozen old Runs may name remote pages not produced in this preview.
        # This fallback is read-only and the outer store verifies their SHA.
        return await self.original.aload_canonical(ref, run_id=self.materials.run_id, kind=kind)
