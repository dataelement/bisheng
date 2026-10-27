"""Tenant-scoped workbench metadata and import tasks."""

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from .models import MarketWorkbench, MarketWorkbenchImport, MarketWorkbenchVersion, now
from .workbench_bundle import compare_semver


class WorkbenchConflictError(ValueError):
    pass


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
        if not reason and same and same.digest != digest:
            reason = "version_conflict"
        if not reason and any(
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
                if existing.status == "failed":
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
                return db.exec(query).one().model_dump()
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
                    if workbench.current_version_id != version.id:
                        workbench.current_version_id = version.id
                        workbench.display_name = task.display_name or manifest["display_name"]
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
        result = {
            "id": workbench.id,
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

    def current_version(self, tenant, workbench_id, version_id):
        with self.sessions() as db:
            row = db.exec(
                select(MarketWorkbenchVersion)
                .join(MarketWorkbench, MarketWorkbench.id == MarketWorkbenchVersion.workbench_id)
                .where(
                    MarketWorkbench.tenant_id == tenant,
                    MarketWorkbenchVersion.tenant_id == tenant,
                    MarketWorkbench.id == workbench_id,
                    MarketWorkbench.current_version_id == version_id,
                    MarketWorkbenchVersion.id == version_id,
                )
            ).first()
            return row.model_dump() if row else None
