"""Session lifecycle SQL composed with project metadata in the same transaction."""

from datetime import datetime

from bisheng.chat_session.domain.repositories.project_repository import ProjectRepository, request_digest
from bisheng.common.errcode.chat import ProjectConversationError, ProjectRequestConflictError


class ProjectSessionRepository:
    @staticmethod
    def create(actor, row, project_id, request_id, request_payload):
        digest = request_digest({"project_id": str(project_id), "request": request_payload})
        key = f"first-message:{request_id}"

        def operation(db, clock):
            receipt = ProjectRepository.receipt(db, actor, key)
            if receipt:
                if receipt.digest != digest:
                    raise ProjectRequestConflictError()
                ProjectRepository.conversation(db, actor, receipt.result["chat_id"])
                return {**receipt.result, "revision": str(clock.revision), "replayed": True}
            ProjectRepository.project(db, actor, project_id)
            if row.user_id != actor.user_id or row.tenant_id != actor.tenant_id or row.api_subject_type is not None:
                raise ProjectConversationError()
            db.add(row)
            db.flush()
            ProjectRepository.assign(db, actor, row.chat_id, project_id)
            clock.revision += 1
            db.add(clock)
            result = {"chat_id": row.chat_id}
            ProjectRepository.save_receipt(db, actor, key, "first-message", digest, result, clock.revision)
            return {**result, "revision": str(clock.revision), "replayed": False}

        return ProjectRepository.transaction(actor, operation)

    @staticmethod
    def rename(actor, chat_id, name, *, only_if_default=False):
        def operation(db, clock):
            row = ProjectRepository.conversation(db, actor, chat_id)
            if only_if_default and row.name not in (None, "", "New Chat"):
                return {"changed": False, "revision": None}
            row.name, row.update_time = name, datetime.now()
            db.add(row)
            revision = None
            if ProjectRepository.membership(db, actor, chat_id):
                clock.revision += 1
                db.add(clock)
                revision = str(clock.revision)
            return {"changed": True, "revision": revision}

        return ProjectRepository.transaction(actor, operation)

    @staticmethod
    def soft_delete(actor, chat_id):
        def operation(db, clock):
            row = ProjectRepository.conversation(db, actor, chat_id, include_deleted=True)
            row.is_delete, row.update_time = True, datetime.now()
            db.add(row)
            member = ProjectRepository.membership(db, actor, chat_id)
            if member:
                db.delete(member)
                clock.revision += 1
                db.add(clock)
                return str(clock.revision)
            return None

        return ProjectRepository.transaction(actor, operation)
