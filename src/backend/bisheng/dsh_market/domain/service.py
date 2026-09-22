import hashlib
import time

from .bundle import BundleError, validate_bundle
from .lease import sign_policy
from .repository import ConflictError


class MarketService:
    def __init__(self, repository, storage):
        self.repository = repository
        self.storage = storage

    def list_plugins(self, tenant, query="", status="all", page=1, size=20, employee=False):
        return self.repository.list(tenant, query, status, page, size, employee)

    def detail(self, tenant, plugin_id):
        plugin = self.repository.get(tenant, plugin_id)
        if plugin is None:
            raise LookupError("Plugin not found")
        return plugin

    def imports(self, tenant):
        return self.repository.imports(tenant)

    def devices(self, tenant):
        return self.repository.devices(tenant)

    def synchronize(self, tenant, user, device, plugins):
        self.repository.report(tenant, user, device, plugins)
        current = int(time.time())
        return sign_policy(
            {
                "tenant_id": str(tenant),
                "user_id": str(user),
                "device_id": device,
                "issued_at": current,
                "expires_at": current + 3600,
                "policies": self.repository.policies(tenant),
            }
        )

    def preview_bundle(self, tenant, data):
        manifest = validate_bundle(data)
        return self.repository.preview(tenant, manifest, hashlib.sha256(data).hexdigest())

    def import_bundle(self, tenant, actor, data):
        digest = hashlib.sha256(data).hexdigest()
        self.storage.put(tenant, digest, data)
        task = self.repository.create_import(tenant, actor, digest)
        return self.validate_import(tenant, task["id"])

    def validate_import(self, tenant, task_id):
        task = self.repository.get_import(tenant, task_id)
        if task is None:
            raise LookupError("Import not found")
        if task["status"] != "validating":
            return task
        data = self.storage.get(tenant, task["digest"])
        try:
            if hashlib.sha256(data).hexdigest() != task["digest"]:
                raise BundleError("Artifact digest mismatch")
            manifest = validate_bundle(data)
        except BundleError as exc:
            return self.repository.finish_import(tenant, task_id, error=str(exc))
        return self.repository.finish_import(tenant, task_id, manifest, len(data))

    def change(self, tenant, actor, plugin_id, revision, action, version_id=None):
        plugin = self.repository.get(tenant, plugin_id)
        if plugin is None:
            raise LookupError("Plugin not found")
        if plugin["revision"] != revision:
            raise ConflictError("Plugin state changed; refresh and retry")
        if action == "publish":
            version = next((v for v in plugin["versions"] if v["id"] == version_id), None)
            if version is None:
                raise LookupError("Version not found")
            data = self.storage.get(tenant, version["digest"])
            if hashlib.sha256(data).hexdigest() != version["digest"]:
                raise BundleError("Artifact digest mismatch")
            validate_bundle(data)
        if action == "unpublish" and plugin["current_version_id"] is None:
            raise ConflictError("Plugin has no published version")
        return self.repository.transition(tenant, actor, plugin_id, revision, action, version_id)

    def download(self, tenant, plugin_id, version_id):
        plugin = self.repository.get(tenant, plugin_id)
        if plugin is None or plugin["disabled"] or plugin["current_version_id"] != version_id:
            raise LookupError("Published version not found")
        version = next(v for v in plugin["versions"] if v["id"] == version_id)
        data = self.storage.get(tenant, version["digest"])
        if hashlib.sha256(data).hexdigest() != version["digest"]:
            raise BundleError("Artifact digest mismatch")
        current = self.repository.get(tenant, plugin_id)
        if current is None or current["disabled"] or current["current_version_id"] != version_id:
            raise ConflictError("Plugin state changed; refresh and retry")
        return data, version["digest"]
