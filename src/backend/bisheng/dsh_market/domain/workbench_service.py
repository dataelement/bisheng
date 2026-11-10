"""Workbench upload and authenticated artifact delivery."""

import hashlib

from .workbench_bundle import WorkbenchBundleError, validate_workbench_bundle


class WorkbenchArtifactError(ValueError):
    pass


class WorkbenchService:
    def __init__(self, repository, storage):
        self.repository = repository
        self.storage = storage

    def preview(self, tenant, data):
        manifest = validate_workbench_bundle(data)
        return self.repository.preview(tenant, manifest, hashlib.sha256(data).hexdigest())

    def import_bundle(self, tenant, actor, data, display_name=None):
        manifest = validate_workbench_bundle(data)
        if display_name is not None:
            display_name = display_name.strip()
            if not display_name or len(display_name) > 128:
                raise WorkbenchBundleError("WB-05: Invalid display name")
        digest = hashlib.sha256(data).hexdigest()
        self.storage.put(tenant, digest, data)
        task = self.repository.create_import(tenant, actor, digest, display_name)
        if task["status"] == "completed":
            return task
        return self.repository.finish_import(tenant, task["id"], manifest, len(data))

    def resume(self, tenant, task_id):
        task = self.repository.retry_import(tenant, task_id)
        if task["status"] == "completed":
            return task
        try:
            data = self.storage.get(tenant, task["digest"])
        except FileNotFoundError as exc:
            raise WorkbenchArtifactError("Workbench import archive missing") from exc
        try:
            if data is None or hashlib.sha256(data).hexdigest() != task["digest"]:
                raise WorkbenchBundleError("WB-01: Artifact digest mismatch")
            manifest = validate_workbench_bundle(data)
        except WorkbenchBundleError as exc:
            return self.repository.finish_import(tenant, task_id, error=str(exc))
        return self.repository.finish_import(tenant, task_id, manifest, len(data))

    def imports(self, tenant):
        return self.repository.imports(tenant)

    def list(self, tenant, page=1, size=20):
        return self.repository.list(tenant, page, size)

    def detail(self, tenant, workbench_id):
        result = self.repository.get(tenant, workbench_id)
        if result is None:
            raise LookupError("Workbench not found")
        return result

    def download(self, tenant, workbench_id, version_id):
        version = self.repository.current_version(tenant, workbench_id, version_id)
        if version is None:
            raise LookupError("Current workbench version not found")
        try:
            data = self.storage.get(tenant, version["digest"])
        except FileNotFoundError as exc:
            raise WorkbenchArtifactError("Workbench artifact missing") from exc
        if data is None or len(data) != version["size"] or hashlib.sha256(data).hexdigest() != version["digest"]:
            raise WorkbenchArtifactError("Workbench artifact digest mismatch")
        if self.repository.current_version(tenant, workbench_id, version_id) is None:
            raise WorkbenchArtifactError("Workbench version changed")
        return data, version["digest"]
