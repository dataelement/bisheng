from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import case, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_background_job import KnowledgeBackgroundJob as Job
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.repositories.interfaces.knowledge_background_repository import (
    KnowledgeBackgroundRepository,
)


class KnowledgeBackgroundRepositoryImpl(KnowledgeBackgroundRepository):
    MAX_ATTEMPTS = 8

    def __init__(self, session):
        self.session = session

    @staticmethod
    def key(tenant_id: int, kind: str, identity: str) -> str:
        return sha256(f"{tenant_id}:{kind}:{identity}".encode()).hexdigest()

    def request(self, *, tenant_id: int, kind: str, identity: str, payload: dict, parent_id: str | None = None) -> str:
        job_id = self.key(tenant_id, kind, identity)
        if self.session.get(Job, job_id) is None:
            try:
                with self.session.begin_nested():
                    self.session.add(
                        Job(id=job_id, tenant_id=tenant_id, kind=kind, payload=payload, parent_id=parent_id)
                    )
                    self.session.flush()
            except IntegrityError:
                if self.session.get(Job, job_id) is None:
                    raise
        return job_id

    def due(self, limit: int = 100) -> list[tuple[str, int]]:
        now = datetime.now()
        self.session.execute(
            update(Job)
            .where(Job.status == "processing", Job.lease_until <= now)
            .values(
                status=case((Job.attempts >= self.MAX_ATTEMPTS, "dead"), else_="pending"),
                lease_owner=None,
                lease_until=None,
                next_retry_at=now + timedelta(minutes=5),
                last_error="worker_interrupted",
                update_time=now,
            )
        )
        rows = self.session.exec(
            select(Job.id, Job.tenant_id)
            .where(
                Job.status.in_(["pending", "waiting"]),
                or_(Job.next_retry_at.is_(None), Job.next_retry_at <= now),
            )
            .order_by(Job.next_retry_at, Job.create_time, Job.id)
            .limit(limit)
        ).all()
        return [(str(row[0]), int(row[1])) for row in rows]

    def claim(self, job_id: str, owner: str, now: datetime) -> Job | None:
        from bisheng.core.context.tenant import get_current_tenant_id

        job = self.session.exec(
            select(Job).where(Job.id == job_id).with_for_update().execution_options(populate_existing=True)
        ).first()
        tenant_id = get_current_tenant_id()
        if job is not None and tenant_id is not None and job.tenant_id != int(tenant_id):
            raise ValueError("background job tenant context mismatch")
        if job is None or job.status not in {"pending", "waiting"} or (job.next_retry_at and job.next_retry_at > now):
            return None
        if job.attempts >= self.MAX_ATTEMPTS:
            job.status = "dead"
            return None
        job.attempts += 1
        job.status, job.lease_owner = "processing", owner
        job.lease_until = now + timedelta(minutes=5)
        self.session.flush()
        return Job.model_validate(job.model_dump())

    def settle(self, job_id: str, owner: str, *, status: str, payload: dict, error: str | None = None) -> bool:
        now = datetime.now()
        values = dict(status=status, payload=payload, last_error=error, update_time=now)
        if status == "waiting" and error is None:
            # 成功推进游标或正常等待不算失败; 崩溃没有结算, 已预扣次数保留。
            values["attempts"] = case((Job.attempts > 0, Job.attempts - 1), else_=0)
        if status != "processing":
            values.update(
                lease_owner=None,
                lease_until=None,
                next_retry_at=now + timedelta(minutes=5) if status in {"pending", "waiting"} else None,
            )
        result = self.session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == "processing",
                Job.lease_owner == owner,
                Job.lease_until > now,
            )
            .values(**values)
        )
        return result.rowcount == 1

    def files(self, ids: list[int]) -> list[KnowledgeFile]:
        return list(self.session.exec(select(KnowledgeFile).where(KnowledgeFile.id.in_(ids))).all()) if ids else []

    def children_statuses(self, parent_id: str) -> list[str]:
        return list(self.session.exec(select(Job.status).where(Job.parent_id == parent_id)).all())

    def container_entries(self, *, space_id: int, prefix: str | None, after_id: int) -> list[KnowledgeFile]:
        statement = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == space_id,
            KnowledgeFile.id > after_id,
            KnowledgeFile.reference_document_id.is_not(None),
            KnowledgeFile.entry_type.in_(["manager", "publish", "share"]),
        )
        if prefix:
            statement = statement.where(
                or_(KnowledgeFile.file_level_path == prefix, KnowledgeFile.file_level_path.like(f"{prefix}/%"))
            )
        return list(self.session.exec(statement.order_by(KnowledgeFile.id).limit(100)).all())

    def request_auto_publish(self, file: KnowledgeFile) -> str | None:
        if file.status != 2 or file.deleted_at is not None or file.file_type != 1:
            return None
        if file.entry_type not in {None, "manager"} or not file.file_subcategory_code:
            return None
        if file.entry_type == "manager" and (file.entry_status != "active" or file.reference_document_id is None):
            return None
        return self.request(
            tenant_id=int(file.tenant_id or 1),
            kind="auto_publish",
            identity=f"{file.id}:{file.md5}:{file.split_rule}:{file.file_subcategory_code}",
            payload={"file_id": int(file.id)},
        )

    def existing_auto_publish_projections(self, file_id: int) -> list[int]:
        source = self.session.get(KnowledgeFile, file_id)
        if source is None or source.reference_document_id is None or source.deleted_at is not None:
            return []
        entry = self.session.exec(
            select(KnowledgeFile)
            .where(
                KnowledgeFile.reference_document_id == source.reference_document_id,
                KnowledgeFile.entry_type == "publish",
                KnowledgeFile.entry_status == "active",
                KnowledgeFile.deleted_at.is_(None),
                KnowledgeFile.approval_instance_id >= -(file_id * 10000 + 9999),
                KnowledgeFile.approval_instance_id <= -(file_id * 10000),
            )
            .order_by(KnowledgeFile.id.desc())
            .limit(1)
        ).first()
        return [file_id, int(entry.id)] if entry is not None else []

    def request_container(self, folder: KnowledgeFile, deleted_at: datetime) -> str:
        deleted_at = deleted_at.replace(microsecond=0)
        ancestor_ids = [int(value) for value in (folder.file_level_path or "").split("/") if value.isdecimal()]
        ancestors = {int(item.id): item for item in self.files(ancestor_ids)}
        for ancestor_id in ancestor_ids:
            ancestor = ancestors.get(ancestor_id)
            if (
                ancestor is not None
                and ancestor.file_type == FileType.DIR.value
                and ancestor.knowledge_id == folder.knowledge_id
                and ancestor.deleted_at is not None
                and ancestor.deleted_at.replace(microsecond=0) == deleted_at
            ):
                # 同次删除的子目录复用根目录意图, 避免旧消息重复扫描整个子树。
                folder = ancestor
                break
        prefix = f"{folder.file_level_path}/{folder.id}"
        return self.request(
            tenant_id=int(folder.tenant_id or 1),
            kind="container",
            identity=f"{folder.id}:{deleted_at.isoformat()}",
            payload={
                "space_id": folder.knowledge_id,
                "folder_id": folder.id,
                "prefix": prefix,
                "deleted_at": deleted_at.isoformat(),
                "cursor": 0,
            },
        )

    def request_delete(
        self,
        *,
        tenant_id: int,
        knowledge: Knowledge | None,
        files: list[dict],
        artifacts: list[dict],
        clear_minio: bool = True,
    ) -> list[str]:
        ids = []
        for file in files:
            file_id = int(file["id"])
            ids.append(
                self.request(
                    tenant_id=tenant_id,
                    kind="delete_file",
                    identity=str(file_id),
                    payload={
                        "file_id": file_id,
                        "knowledge": knowledge.model_dump() if knowledge else None,
                        "file": file,
                        "artifacts": [a for a in artifacts if int(a.get("knowledge_file_id", 0)) == file_id],
                        "clear_minio": clear_minio,
                        "completed_stages": [],
                    },
                )
            )
        return ids

    def object_is_referenced(self, object_name: str) -> bool:
        from sqlalchemy import Text, cast

        from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import KnowledgeFilePdfArtifact

        statement = (
            select(KnowledgeFile.id)
            .where(
                or_(
                    KnowledgeFile.object_name == object_name,
                    KnowledgeFile.preview_file_object_name == object_name,
                    KnowledgeFile.bbox_object_name == object_name,
                    KnowledgeFile.thumbnails == object_name,
                    cast(KnowledgeFile.user_metadata, Text).contains(object_name, autoescape=True),
                )
            )
            .limit(1)
        )
        if self.session.exec(statement).first() is not None:
            return True
        return (
            self.session.exec(
                select(KnowledgeFilePdfArtifact.id)
                .join(
                    KnowledgeFile,
                    KnowledgeFile.id == KnowledgeFilePdfArtifact.knowledge_file_id,
                )
                .where(
                    or_(
                        KnowledgeFilePdfArtifact.object_name == object_name,
                        KnowledgeFilePdfArtifact.source_object_name == object_name,
                    )
                )
                .limit(1)
            ).first()
            is not None
        )
