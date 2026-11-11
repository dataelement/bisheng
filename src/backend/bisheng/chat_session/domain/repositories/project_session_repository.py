"""Conversation creation composed with project membership in the same transaction."""

from bisheng.chat_session.domain.repositories.project_repository import ProjectRepository
from bisheng.common.errcode.chat import ProjectConversationError


class ProjectSessionRepository:
    @staticmethod
    def create(actor, row, project_id):
        def operation(db):
            ProjectRepository.project(db, actor, project_id)
            if row.user_id != actor.user_id or row.tenant_id != actor.tenant_id or row.api_subject_type is not None:
                raise ProjectConversationError()
            db.add(row)
            db.flush()
            ProjectRepository.assign(db, actor, row.chat_id, project_id)
            return row.chat_id

        return ProjectRepository.transaction(actor, operation)
