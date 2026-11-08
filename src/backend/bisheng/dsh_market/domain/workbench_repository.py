"""Tenant-scoped workbench metadata and import tasks."""

import re

from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from .models import MarketWorkbench, MarketWorkbenchImport, MarketWorkbenchVersion, now
from .workbench_bundle import (
    MAX_SCREENSHOT_BYTES,
    MAX_SCREENSHOT_DIMENSION,
    MAX_SCREENSHOT_PIXELS,
    MAX_SCREENSHOTS,
    MAX_SCREENSHOTS_BYTES,
    WorkbenchBundleError,
    _screenshot_path,
    compare_semver,
    screenshot_id,
)


class WorkbenchConflictError(ValueError):
    pass


class WorkbenchArtifactError(ValueError):
    pass


def screenshot_metadata(manifest, artifact_digest):
    if not isinstance(manifest, dict) or not isinstance(manifest.get("screenshots", []), list):
        raise WorkbenchArtifactError("Invalid workbench screenshot metadata")
    images = manifest.get("screenshots", [])
    if len(images) > MAX_SCREENSHOTS:
        raise WorkbenchArtifactError("Invalid workbench screenshot metadata")
    seen_ids, seen_paths, total = set(), set(), 0
    for image in images:
        if (
            not isinstance(image, dict)
            or any(not isinstance(image.get(key), str) for key in ("id", "path", "sha256", "media_type", "alt"))
            or any(type(image.get(key)) is not int or image[key] <= 0 for key in ("width", "height", "bytes"))
        ):
            raise WorkbenchArtifactError("Invalid workbench screenshot metadata")
        path, alt = image["path"], image["alt"]
        if any(0xD800 <= ord(char) <= 0xDFFF for char in path + alt):
            raise WorkbenchArtifactError("Invalid workbench screenshot metadata")
        try:
            normalized, expected = _screenshot_path(path, "screenshot.path")
        except WorkbenchBundleError as exc:
            raise WorkbenchArtifactError("Invalid workbench screenshot metadata") from exc
        total += image["bytes"]
        if (
            not isinstance(artifact_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", artifact_digest)
            or not re.fullmatch(r"[0-9a-f]{64}", image["sha256"])
            or not re.fullmatch(r"[0-9a-f]{64}", image["id"])
            or normalized != path
            or image["media_type"] != expected[1]
            or image["id"] != screenshot_id(artifact_digest, path, image["sha256"])
            or image["id"] in seen_ids
            or path in seen_paths
            or image["width"] > MAX_SCREENSHOT_DIMENSION
            or image["height"] > MAX_SCREENSHOT_DIMENSION
            or image["width"] * image["height"] > MAX_SCREENSHOT_PIXELS
            or image["bytes"] > MAX_SCREENSHOT_BYTES
            or total > MAX_SCREENSHOTS_BYTES
            or len(alt) > 256
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in alt)
        ):
            raise WorkbenchArtifactError("Invalid workbench screenshot metadata")
        seen_ids.add(image["id"])
        seen_paths.add(path)
    return images


class WorkbenchRepository:
    def __init__(self, session_factory):
        self.sessions = session_factory

    @staticmethod
    def _candidate(db, tenant, manifest, digest, lock=False):
        identity = manifest["identity_key"]
        package_name = manifest["package_name"]
        query = select(MarketWorkbench).where(
            MarketWorkbench.tenant_id == tenant,
            or_(MarketWorkbench.identity_key == identity, MarketWorkbench.package_name == package_name),
        )
        rows = db.exec(query.with_for_update() if lock else query).all()
        conflict = any(row.identity_key != identity or row.package_name != package_name for row in rows)
        workbench = next((row for row in rows if row.identity_key == identity), None)
        versions = (
            db.exec(
                select(MarketWorkbenchVersion).where(
                    MarketWorkbenchVersion.tenant_id == tenant,
                    MarketWorkbenchVersion.workbench_id == workbench.id,
                )
            ).all()
            if workbench
            else []
        )
        same = next((row for row in versions if row.version == manifest["version"]), None)
        current = next((row for row in versions if row.id == workbench.current_version_id), None) if workbench else None
        reason = "identity_conflict" if conflict else ""
        # A deleted workbench can be restored with equivalent build metadata.
        # Exact reimports of its restored current version remain allowed.
        check_equivalent = workbench and workbench.current_version_id is not None and (
            current is None or current.version != manifest["version"]
        )
        if not reason and check_equivalent and any(
            row.version != manifest["version"] and compare_semver(manifest["version"], row.version) == 0
            for row in versions
        ):
            reason = "version_conflict"
        if not reason and versions and any(compare_semver(manifest["version"], row.version) < 0 for row in versions):
            reason = "lower_version"
        return (
            workbench,
            same,
            {
                "package_name": package_name,
                "identity_kind": manifest["identity_kind"],
                "workbench_key": manifest["workbench_key"],
                "legacy_id": manifest["legacy_id"],
                "incoming_version": manifest["version"],
                "current_version": current.version if current else None,
                "suggested_display_name": manifest["display_name"],
                "allowed": not reason,
                "duplicate": bool(same and same.digest == digest),
                "overwrite": bool(not reason and same and same.digest != digest),
                "reason": reason,
                "warnings": manifest["warnings"],
            },
        )

    def preview(self, tenant, manifest, digest):
        with self.sessions() as db:
            return self._candidate(db, tenant, manifest, digest)[2]

    def create_import(self, tenant, actor, digest, display_name):
        with self.sessions() as db:
            query = select(MarketWorkbenchImport).where(
                MarketWorkbenchImport.tenant_id == tenant, MarketWorkbenchImport.digest == digest
            )
            existing = db.exec(query.with_for_update()).first()
            if existing:
                # Active reimports must reapply bytes after an overwrite or deletion.
                # Resuming an existing completed task keeps its separate no-op behavior.
                if existing.status in {"failed", "completed"}:
                    existing.status, existing.error, existing.error_code = "validating", "", ""
                    existing.actor_id, existing.display_name, existing.created_at = actor, display_name, now()
                    db.add(existing)
                    db.commit()
                    db.refresh(existing)
                return existing.model_dump()
            task = MarketWorkbenchImport(tenant_id=tenant, actor_id=actor, digest=digest, display_name=display_name)
            db.add(task)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                # The winning task may already be completed and overwritten or deleted.
                # Re-enter the active-import reset path rather than returning stale success.
                db.exec(query.with_for_update()).one()
                db.rollback()
                return self.create_import(tenant, actor, digest, display_name)
            db.refresh(task)
            return task.model_dump()

    def imports(self, tenant):
        with self.sessions() as db:
            return [
                row.model_dump()
                for row in db.exec(
                    select(MarketWorkbenchImport)
                    .where(MarketWorkbenchImport.tenant_id == tenant)
                    .order_by(MarketWorkbenchImport.created_at.desc(), MarketWorkbenchImport.id)
                    .limit(100)
                ).all()
            ]

    def get_import(self, tenant, task_id):
        with self.sessions() as db:
            row = db.exec(
                select(MarketWorkbenchImport).where(
                    MarketWorkbenchImport.tenant_id == tenant, MarketWorkbenchImport.id == task_id
                )
            ).first()
            return row.model_dump() if row else None

    def retry_import(self, tenant, task_id):
        with self.sessions() as db:
            row = db.exec(
                select(MarketWorkbenchImport)
                .where(MarketWorkbenchImport.tenant_id == tenant, MarketWorkbenchImport.id == task_id)
                .with_for_update()
            ).first()
            if row is None:
                raise LookupError("Workbench import not found")
            if row.status == "failed":
                row.status, row.error, row.error_code = "validating", "", ""
                db.add(row)
                db.commit()
                db.refresh(row)
            return row.model_dump()

    def finish_import(self, tenant, task_id, manifest=None, size=0, error=""):
        with self.sessions() as db:
            task = db.exec(
                select(MarketWorkbenchImport)
                .where(MarketWorkbenchImport.tenant_id == tenant, MarketWorkbenchImport.id == task_id)
                .with_for_update()
            ).one()
            if task.status != "validating":
                return task.model_dump()
            if error:
                task.status, task.error = "failed", error[:512]
                task.error_code = error.split(":", 1)[0][:32]
            else:
                workbench, version, preview = self._candidate(db, tenant, manifest, task.digest, lock=True)
                if not preview["allowed"]:
                    task.status, task.error_code, task.error = "failed", preview["reason"], preview["reason"]
                else:
                    if workbench is None:
                        workbench = MarketWorkbench(
                            tenant_id=tenant,
                            identity_key=manifest["identity_key"],
                            identity_kind=manifest["identity_kind"],
                            workbench_key=manifest["workbench_key"],
                            legacy_id=manifest["legacy_id"],
                            package_name=manifest["package_name"],
                            display_name=task.display_name or manifest["display_name"],
                            description=manifest["description"],
                        )
                        db.add(workbench)
                        try:
                            db.flush()
                        except IntegrityError as exc:
                            db.rollback()
                            raise WorkbenchConflictError("Concurrent workbench import; refresh and retry") from exc
                    if version is None:
                        version = MarketWorkbenchVersion(
                            tenant_id=tenant,
                            workbench_id=workbench.id,
                            version=manifest["version"],
                            digest=task.digest,
                            size=size,
                            manifest=manifest,
                        )
                        db.add(version)
                    changed = version.digest != task.digest or version.size != size or version.manifest != manifest
                    version.digest, version.size, version.manifest = task.digest, size, manifest
                    db.add(version)
                    display_name = task.display_name or (
                        workbench.display_name if preview["duplicate"] else manifest["display_name"]
                    )
                    if (
                        changed
                        or workbench.current_version_id != version.id
                        or workbench.display_name != display_name
                        or workbench.description != manifest["description"]
                    ):
                        workbench.current_version_id = version.id
                        workbench.display_name = display_name
                        workbench.description = manifest["description"]
                        workbench.updated_at = now()
                        workbench.revision += 1
                        db.add(workbench)
                    task.status, task.version_id = "completed", version.id
            db.add(task)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise WorkbenchConflictError("Concurrent workbench import; refresh and retry") from exc
            db.refresh(task)
            return task.model_dump()

    @staticmethod
    def _view(db, tenant, workbench, detail=False):
        version = db.exec(
            select(MarketWorkbenchVersion).where(
                MarketWorkbenchVersion.tenant_id == tenant,
                MarketWorkbenchVersion.workbench_id == workbench.id,
                MarketWorkbenchVersion.id == workbench.current_version_id,
            )
        ).first()
        if version is None:
            raise LookupError("Current workbench version not found")
        current = {"id": version.id, "version": version.version}
        if detail:
            current.update(
                sha256=version.digest,
                size_bytes=version.size,
                artifact_url=f"/api/v1/dsh/market/workbenches/{workbench.id}/versions/{version.id}/artifact",
            )
        screenshots = [
            {
                **{key: image[key] for key in ("id", "sha256", "media_type", "width", "height", "bytes", "alt")},
                "url": f"/api/v1/dsh/market/workbenches/{workbench.id}/versions/{version.id}/screenshots/{image['id']}",
            }
            for image in screenshot_metadata(version.manifest, version.digest)
        ]
        result = {
            "screenshots": screenshots,
            "cover": screenshots[0] if screenshots else None,
            "id": workbench.id,
            "revision": workbench.revision,
            "identity_kind": workbench.identity_kind,
            "workbench_key": workbench.workbench_key,
            "legacy_id": workbench.legacy_id,
            "package_name": workbench.package_name,
            "display_name": workbench.display_name,
            "description": workbench.description,
            "current_version": current,
            "verification_level": "static",
            "updated_at": workbench.updated_at,
        }
        if detail:
            result["package_metadata"] = version.manifest["package_metadata"]
        return result

    def list(self, tenant, page=1, size=20):
        with self.sessions() as db:
            clauses = (MarketWorkbench.tenant_id == tenant, MarketWorkbench.current_version_id.is_not(None))
            total = db.exec(select(func.count()).select_from(MarketWorkbench).where(*clauses)).one()
            rows = db.exec(
                select(MarketWorkbench)
                .where(*clauses)
                .order_by(MarketWorkbench.updated_at.desc(), MarketWorkbench.id)
                .offset((page - 1) * size)
                .limit(size)
            ).all()
            return {"data": [self._view(db, tenant, row) for row in rows], "total": total}

    def get(self, tenant, workbench_id):
        with self.sessions() as db:
            row = db.exec(
                select(MarketWorkbench).where(
                    MarketWorkbench.tenant_id == tenant,
                    MarketWorkbench.id == workbench_id,
                    MarketWorkbench.current_version_id.is_not(None),
                )
            ).first()
            return self._view(db, tenant, row, detail=True) if row else None

    def delete(self, tenant, workbench_id, revision):
        with self.sessions() as db:
            row = db.exec(
                select(MarketWorkbench).where(
                    MarketWorkbench.tenant_id == tenant,
                    MarketWorkbench.id == workbench_id,
                    MarketWorkbench.current_version_id.is_not(None),
                )
            ).first()
            if row is None:
                raise LookupError("Workbench not found")
            result = db.execute(
                update(MarketWorkbench)
                .where(
                    MarketWorkbench.tenant_id == tenant,
                    MarketWorkbench.id == workbench_id,
                    MarketWorkbench.current_version_id.is_not(None),
                    MarketWorkbench.revision == revision,
                )
                .values(current_version_id=None, revision=MarketWorkbench.revision + 1, updated_at=now())
            )
            if result.rowcount != 1:
                db.rollback()
                raise WorkbenchConflictError("Workbench changed; refresh and retry")
            db.commit()
            return {"id": workbench_id, "deleted": True}

    def current_version(self, tenant, workbench_id, version_id):
        snapshot = self.current_version_snapshot(tenant, workbench_id, version_id)
        return snapshot[0] if snapshot else None

    def current_version_snapshot(self, tenant, workbench_id, version_id):
        with self.sessions() as db:
            row = db.exec(
                select(MarketWorkbenchVersion, MarketWorkbench.revision)
                .join(MarketWorkbench, MarketWorkbench.id == MarketWorkbenchVersion.workbench_id)
                .where(
                    MarketWorkbench.tenant_id == tenant,
                    MarketWorkbenchVersion.tenant_id == tenant,
                    MarketWorkbench.id == workbench_id,
                    MarketWorkbench.current_version_id == version_id,
                    MarketWorkbenchVersion.id == version_id,
                )
            ).first()
            return (row[0].model_dump(), row[1]) if row else None
