"""Workbench upload and authenticated artifact delivery."""

import hashlib

from .workbench_bundle import (
    WorkbenchBundleError,
    read_workbench_screenshot,
    screenshot_id,
    validate_workbench_bundle,
)
from .workbench_repository import WorkbenchArtifactError, screenshot_metadata


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

    def delete(self, tenant, actor, workbench_id, revision):
        return self.repository.delete(tenant, workbench_id, revision)

    def download(self, tenant, workbench_id, version_id):
        snapshot = self.repository.current_version_snapshot(tenant, workbench_id, version_id)
        if snapshot is None:
            raise LookupError("Current workbench version not found")
        return self._download_snapshot(tenant, workbench_id, version_id, snapshot)

    def _check_snapshot(self, tenant, workbench_id, version_id, snapshot):
        current = self.repository.current_version_snapshot(tenant, workbench_id, version_id)
        version, revision = snapshot
        if (
            current is None
            or current[1] != revision
            or any(current[0][key] != version[key] for key in ("id", "digest"))
        ):
            raise WorkbenchArtifactError("Workbench version changed")

    def _download_snapshot(self, tenant, workbench_id, version_id, snapshot):
        version, _revision = snapshot
        try:
            data = self.storage.get(tenant, version["digest"])
        except FileNotFoundError as exc:
            raise WorkbenchArtifactError("Workbench artifact missing") from exc
        if data is None or len(data) != version["size"] or hashlib.sha256(data).hexdigest() != version["digest"]:
            raise WorkbenchArtifactError("Workbench artifact digest mismatch")
        self._check_snapshot(tenant, workbench_id, version_id, snapshot)
        return data, version["digest"]

    def screenshot(self, tenant, workbench_id, version_id, image_id):
        snapshot = self.repository.current_version_snapshot(tenant, workbench_id, version_id)
        if snapshot is None:
            raise LookupError("Current workbench version not found")
        version, _revision = snapshot
        metadata = next(
            (image for image in screenshot_metadata(version["manifest"], version["digest"]) if image["id"] == image_id),
            None,
        )
        if metadata is None:
            raise LookupError("Workbench screenshot not found")
        if screenshot_id(version["digest"], metadata["path"], metadata["sha256"]) != image_id:
            raise WorkbenchArtifactError("Workbench screenshot binding mismatch")
        data, _digest = self._download_snapshot(tenant, workbench_id, version_id, snapshot)
        try:
            raw = read_workbench_screenshot(data, metadata)
        except WorkbenchBundleError as exc:
            raise WorkbenchArtifactError("Workbench screenshot unavailable or invalid") from exc
        # Decoding can take time. Recheck after decoding as well as after storage IO.
        self._check_snapshot(tenant, workbench_id, version_id, snapshot)
        return raw, metadata
