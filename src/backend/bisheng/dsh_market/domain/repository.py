"""Tenant predicates are explicit on reads and writes, including CAS updates."""

from sqlalchemy import false, func, or_, true, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from .models import MarketAudit, MarketDevice, MarketImport, MarketPlugin, MarketVersion, now


class ConflictError(ValueError):
    pass


class MarketRepository:
    def __init__(self, session_factory):
        self.sessions = session_factory

    def create_import(self, tenant, actor, digest):
        with self.sessions() as db:
            query = (
                select(MarketImport)
                .where(MarketImport.tenant_id == tenant, MarketImport.digest == digest)
                .with_for_update()
            )
            existing = db.exec(query).first()
            if existing:
                plugin = (
                    db.exec(
                        select(MarketPlugin)
                        .join(MarketVersion, MarketVersion.plugin_id == MarketPlugin.id)
                        .where(
                            MarketPlugin.tenant_id == tenant,
                            MarketVersion.tenant_id == tenant,
                            MarketVersion.id == existing.version_id,
                        )
                        .with_for_update()
                    ).first()
                    if existing.version_id
                    else None
                )
                if existing.status == "failed" or (
                    plugin and (plugin.deleted or plugin.disabled or plugin.current_version_id is None)
                ):
                    existing.status, existing.error = "validating", ""
                    existing.actor_id, existing.created_at = actor, now()
                    db.add(existing)
                    db.commit()
                    db.refresh(existing)
                return existing.model_dump()
            task = MarketImport(tenant_id=tenant, actor_id=actor, digest=digest)
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
                v.model_dump()
                for v in db.exec(
                    select(MarketImport)
                    .where(MarketImport.tenant_id == tenant)
                    .order_by(MarketImport.created_at.desc(), MarketImport.id)
                    .limit(100)
                ).all()
            ]

    def get_import(self, tenant, task_id):
        with self.sessions() as db:
            row = db.exec(
                select(MarketImport).where(MarketImport.tenant_id == tenant, MarketImport.id == task_id)
            ).first()
            return row.model_dump() if row else None

    def finish_import(self, tenant, task_id, manifest=None, size=0, error=""):
        with self.sessions() as db:
            task = db.exec(
                select(MarketImport)
                .where(MarketImport.tenant_id == tenant, MarketImport.id == task_id)
                .with_for_update()
            ).one()
            if task.status != "validating":
                return task.model_dump()
            if error:
                task.status, task.error = "failed", error[:512]
            else:
                meta = manifest["plugin"]
                plugin = db.exec(
                    select(MarketPlugin)
                    .where(MarketPlugin.tenant_id == tenant, MarketPlugin.name == meta["name"])
                    .with_for_update()
                ).first()
                if plugin is None:
                    plugin = MarketPlugin(
                        tenant_id=tenant,
                        name=meta["name"],
                        display_name=meta["display_name"],
                        description=meta["description"],
                    )
                    db.add(plugin)
                    db.flush()
                version = db.exec(
                    select(MarketVersion).where(
                        MarketVersion.tenant_id == tenant,
                        MarketVersion.plugin_id == plugin.id,
                        MarketVersion.version == meta["version"],
                    )
                ).first()
                if version and version.digest != task.digest:
                    task.status, task.error = "failed", "Version already exists with a different digest"
                else:
                    before = {
                        "current_version_id": plugin.current_version_id,
                        "disabled": plugin.disabled,
                        "deleted": plugin.deleted,
                    }
                    fresh = version is None
                    if fresh:
                        version = MarketVersion(
                            tenant_id=tenant,
                            plugin_id=plugin.id,
                            version=meta["version"],
                            digest=task.digest,
                            size=size,
                            manifest=manifest,
                            published_once=True,
                        )
                        db.add(version)
                    if fresh or plugin.deleted or plugin.disabled or plugin.current_version_id is None:
                        plugin.deleted = False
                        version.published_once = True
                        db.add(version)
                        plugin.current_version_id = version.id
                        plugin.disabled = False
                        plugin.display_name = meta["display_name"]
                        plugin.description = meta["description"]
                        plugin.revision += 1
                        plugin.updated_at = now()
                        db.add(plugin)
                        db.add(
                            MarketAudit(
                                tenant_id=tenant,
                                actor_id=task.actor_id,
                                plugin_id=plugin.id,
                                version_id=version.id,
                                action="import",
                                revision=plugin.revision,
                                before=before,
                                after={"current_version_id": version.id, "disabled": False, "deleted": False},
                            )
                        )
                    task.status, task.version_id = "completed", version.id
            db.add(task)
            db.commit()
            db.refresh(task)
            return task.model_dump()

    def list(self, tenant, query="", status="all", page=1, size=20, employee=False):
        with self.sessions() as db:
            clauses = [MarketPlugin.tenant_id == tenant, MarketPlugin.deleted == false()]
            if query:
                escaped = query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                clauses.append(
                    or_(
                        func.lower(MarketPlugin.display_name).like(f"%{escaped}%", escape="\\"),
                        func.lower(MarketPlugin.description).like(f"%{escaped}%", escape="\\"),
                    )
                )
            if employee or status == "published":
                clauses += [MarketPlugin.disabled == false(), MarketPlugin.current_version_id.is_not(None)]
            elif status == "unpublished":
                clauses.append(or_(MarketPlugin.disabled == true(), MarketPlugin.current_version_id.is_(None)))
            total = db.exec(select(func.count()).select_from(MarketPlugin).where(*clauses)).one()
            rows = db.exec(
                select(MarketPlugin)
                .where(*clauses)
                .order_by(MarketPlugin.updated_at.desc(), MarketPlugin.id)
                .offset((page - 1) * size)
                .limit(size)
            ).all()
            return {"data": [self._view(db, tenant, row, employee) for row in rows], "total": total}

    def _view(self, db, tenant, plugin, employee=False):
        result = plugin.model_dump()
        clauses = [MarketVersion.tenant_id == tenant, MarketVersion.plugin_id == plugin.id]
        if employee:
            clauses.append(MarketVersion.id == plugin.current_version_id)
        # Sort scalar identifiers, then hydrate manifests outside the database sort buffer.
        version_ids = db.exec(
            select(MarketVersion.id).where(*clauses).order_by(MarketVersion.created_at.desc(), MarketVersion.id)
        ).all()
        versions = (
            {
                version.id: version
                for version in db.exec(select(MarketVersion).where(*clauses, MarketVersion.id.in_(version_ids))).all()
            }
            if version_ids
            else {}
        )
        result["versions"] = [
            {**v.model_dump(), "manifest": {**v.manifest, "targets": {target: {} for target in v.manifest["targets"]}}}
            for version_id in version_ids
            if (v := versions.get(version_id)) is not None
        ]
        result["status"] = "published" if plugin.current_version_id and not plugin.disabled else "unpublished"
        return result

    def get(self, tenant, plugin_id):
        with self.sessions() as db:
            plugin = db.exec(
                select(MarketPlugin).where(
                    MarketPlugin.tenant_id == tenant, MarketPlugin.id == plugin_id, MarketPlugin.deleted == false()
                )
            ).first()
            return self._view(db, tenant, plugin) if plugin else None

    def transition(self, tenant, actor, plugin_id, revision, action, version_id=None):
        with self.sessions() as db:
            plugin = db.exec(
                select(MarketPlugin)
                .where(
                    MarketPlugin.tenant_id == tenant,
                    MarketPlugin.id == plugin_id,
                    MarketPlugin.revision == revision,
                    MarketPlugin.deleted == false(),
                )
                .with_for_update()
            ).first()
            if plugin is None:
                raise ConflictError("Plugin state changed; refresh and retry")
            before = {
                "current_version_id": plugin.current_version_id,
                "disabled": plugin.disabled,
                "deleted": plugin.deleted,
            }
            values = {"revision": revision + 1, "updated_at": now()}
            if action == "publish":
                version = db.exec(
                    select(MarketVersion).where(
                        MarketVersion.tenant_id == tenant,
                        MarketVersion.plugin_id == plugin_id,
                        MarketVersion.id == version_id,
                    )
                ).one()
                values.update(
                    current_version_id=version.id,
                    disabled=False,
                    display_name=version.manifest["plugin"]["display_name"],
                    description=version.manifest["plugin"]["description"],
                )
                version.published_once = True
                db.add(version)
            elif action == "unpublish":
                values["current_version_id"] = None
            elif action == "delete":
                values.update(deleted=True, current_version_id=None)
            elif action == "disable":
                values.update(disabled=True, current_version_id=None)
            changed = db.execute(
                update(MarketPlugin)
                .where(
                    MarketPlugin.tenant_id == tenant, MarketPlugin.id == plugin_id, MarketPlugin.revision == revision
                )
                .values(**values)
            )
            if changed.rowcount != 1:
                raise ConflictError("Plugin state changed; refresh and retry")
            db.add(
                MarketAudit(
                    tenant_id=tenant,
                    actor_id=actor,
                    plugin_id=plugin_id,
                    version_id=version_id,
                    action=action,
                    revision=revision + 1,
                    before=before,
                    after={key: values.get(key, value) for key, value in before.items()},
                )
            )
            db.commit()
        return {"id": plugin_id, "deleted": True} if action == "delete" else self.get(tenant, plugin_id)

    def audits(self, tenant, plugin_id):
        with self.sessions() as db:
            return [
                v.model_dump()
                for v in db.exec(
                    select(MarketAudit)
                    .where(MarketAudit.tenant_id == tenant, MarketAudit.plugin_id == plugin_id)
                    .order_by(MarketAudit.created_at.desc(), MarketAudit.id)
                    .limit(200)
                ).all()
            ]

    def policies(self, tenant):
        with self.sessions() as db:
            return [
                {
                    "plugin_id": p.id,
                    "name": p.name,
                    "disabled": p.disabled,
                    "revision": p.revision,
                    "current_version_id": p.current_version_id,
                    "versions": [
                        {"id": v.id, "digest": v.digest}
                        for v in db.exec(
                            select(MarketVersion).where(
                                MarketVersion.tenant_id == tenant,
                                MarketVersion.plugin_id == p.id,
                                MarketVersion.published_once == true(),
                            )
                        ).all()
                    ],
                }
                for p in db.exec(select(MarketPlugin).where(MarketPlugin.tenant_id == tenant)).all()
            ]

    def report(self, tenant, user, device, plugins):
        with self.sessions() as db:
            row = db.exec(
                select(MarketDevice)
                .where(MarketDevice.tenant_id == tenant, MarketDevice.user_id == user, MarketDevice.device_id == device)
                .with_for_update()
            ).first()
            if row is None:
                row = MarketDevice(tenant_id=tenant, user_id=user, device_id=device, plugins=plugins)
            row.plugins, row.synced_at = plugins, now()
            db.add(row)
            db.commit()

    def devices(self, tenant):
        with self.sessions() as db:
            return [
                v.model_dump()
                for v in db.exec(
                    select(MarketDevice)
                    .where(MarketDevice.tenant_id == tenant)
                    .order_by(MarketDevice.synced_at.desc())
                    .limit(500)
                ).all()
            ]
