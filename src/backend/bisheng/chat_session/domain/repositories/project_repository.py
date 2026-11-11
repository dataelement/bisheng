"""Short SQL transactions for account-private projects; no network effects under locks."""

from datetime import datetime
from uuid import UUID, uuid5

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from bisheng.chat_session.domain.models.project import ChatProject, ChatProjectMembership
from bisheng.chat_session.domain.schemas.projects import ImportProjects, ProjectAction, ProjectActor
from bisheng.common.errcode.chat import ProjectConversationError, ProjectInputError, ProjectUnavailableError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.core.database import get_sync_db_session
from bisheng.core.database.retry import retry_on_transient_db_conflict
from bisheng.database.models.session import MessageSession

# Fixed namespace: a legacy browser project maps to the same cloud id for the
# same account on every import attempt, which makes re-import a no-op.
LEGACY_PROJECT_NAMESPACE = UUID("8a1f3c52-6a0e-4d55-9b7e-3f0c2d4b9e61")


def legacy_project_id(actor: ProjectActor, legacy_id: str) -> str:
    return str(uuid5(LEGACY_PROJECT_NAMESPACE, f"{actor.tenant_id}:{actor.user_id}:{legacy_id}"))


def decode_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.isascii() or not cursor.isdecimal() or len(cursor) > 9:
        raise ProjectInputError()
    return int(cursor)


class ProjectRepository:
    @staticmethod
    @retry_on_transient_db_conflict()
    def transaction(actor: ProjectActor, operation):
        # A concurrent insert of the same membership or client-generated project id
        # surfaces as IntegrityError; the rolled-back unit re-reads and converges.
        # A conflict that survives the re-read is a key this actor cannot see
        # (another tenant's project id): report it as unavailable, not a 500.
        for attempt in range(2):
            try:
                with tenant_execution_scope(actor.tenant_id), get_sync_db_session() as db:
                    result = operation(db)
                    db.commit()
                    return result
            except IntegrityError as exc:
                if attempt == 1:
                    raise ProjectUnavailableError() from exc
                logger.warning("chat-project insertion conflict; retrying once")

    @staticmethod
    def project(db, actor, project_id, *, include_deleted=False):
        row = db.exec(
            select(ChatProject)
            .where(ChatProject.id == str(project_id), ChatProject.user_id == actor.user_id)
            .with_for_update()
        ).first()
        if row is None or row.tenant_id != actor.tenant_id or (row.deleted_at is not None and not include_deleted):
            raise ProjectUnavailableError()
        return row

    @staticmethod
    def owned_conversation(row, actor) -> bool:
        return (
            row is not None
            and row.user_id == actor.user_id
            and row.tenant_id == actor.tenant_id
            and row.api_subject_type is None
            and not row.is_delete
        )

    @staticmethod
    def conversation(db, actor, chat_id):
        row = db.exec(select(MessageSession).where(MessageSession.chat_id == chat_id).with_for_update()).first()
        if not ProjectRepository.owned_conversation(row, actor):
            raise ProjectConversationError()
        return row

    @staticmethod
    def membership(db, actor, chat_id):
        row = db.exec(
            select(ChatProjectMembership).where(
                ChatProjectMembership.user_id == actor.user_id, ChatProjectMembership.chat_id == chat_id
            )
        ).first()
        if row is not None and row.tenant_id != actor.tenant_id:
            raise ProjectConversationError()
        return row

    @staticmethod
    def assign(db, actor, chat_id, project_id):
        if project_id is not None:
            ProjectRepository.project(db, actor, project_id)
        ProjectRepository.conversation(db, actor, chat_id)
        row = ProjectRepository.membership(db, actor, chat_id)
        if project_id is None:
            if row:
                db.delete(row)
        elif row:
            row.project_id = str(project_id)
            db.add(row)
        else:
            db.add(
                ChatProjectMembership(
                    tenant_id=actor.tenant_id, user_id=actor.user_id, chat_id=chat_id, project_id=str(project_id)
                )
            )

    @classmethod
    def execute(cls, actor: ProjectActor, action: ProjectAction) -> dict:
        def operation(db):
            if action.operation == "import":
                return cls.import_legacy(db, actor, action)
            if action.operation == "create":
                project_id = str(action.project_id)
                existing = db.exec(select(ChatProject).where(ChatProject.id == project_id)).first()
                if existing is not None:
                    # Same account retrying the same create: return it. Anything
                    # else (deleted, or another account's id) is unavailable.
                    if (
                        existing.user_id != actor.user_id
                        or existing.tenant_id != actor.tenant_id
                        or existing.deleted_at is not None
                    ):
                        raise ProjectUnavailableError()
                else:
                    db.add(
                        ChatProject(id=project_id, tenant_id=actor.tenant_id, user_id=actor.user_id, name=action.name)
                    )
                    db.flush()
                if action.chat_id:
                    cls.assign(db, actor, action.chat_id, project_id)
                return {"project_id": project_id}
            if action.operation == "rename":
                row = cls.project(db, actor, action.project_id)
                row.name, row.updated_at = action.name, datetime.now()
                db.add(row)
                return {"project_id": row.id}
            if action.operation == "delete":
                row = cls.project(db, actor, action.project_id, include_deleted=True)
                row.deleted_at = row.deleted_at or datetime.now()
                row.updated_at = datetime.now()
                db.add(row)
                for membership in db.exec(
                    select(ChatProjectMembership).where(
                        ChatProjectMembership.user_id == actor.user_id, ChatProjectMembership.project_id == row.id
                    )
                ).all():
                    db.delete(membership)
                return {"project_id": row.id}
            cls.assign(db, actor, action.chat_id, action.project_id)
            return {"chat_id": action.chat_id, "project_id": str(action.project_id) if action.project_id else None}

        return {"outcome": cls.transaction(actor, operation)}

    @classmethod
    def import_legacy(cls, db, actor, action: ImportProjects) -> dict:
        """Import a legacy project only for the account that owns its conversations.

        The browser record carries no account; ownership is inferred from the
        conversations. A project with no conversation owned by this account
        (including an empty one) is not imported. An already-imported project
        is skipped entirely, so cloud edits made after the first import win.
        """
        chat_ids = list({item.chat_id for item in action.memberships})
        sessions = {
            row.chat_id: row
            for row in (
                db.exec(select(MessageSession).where(col(MessageSession.chat_id).in_(chat_ids))).all()
                if chat_ids
                else []
            )
        }
        assigned = {
            row.chat_id
            for row in (
                db.exec(
                    select(ChatProjectMembership).where(
                        ChatProjectMembership.user_id == actor.user_id,
                        col(ChatProjectMembership.chat_id).in_(chat_ids),
                    )
                ).all()
                if chat_ids
                else []
            )
        }
        by_project: dict[str, list[str]] = {}
        for item in action.memberships:
            by_project.setdefault(item.legacy_project_id, []).append(item.chat_id)

        results = []
        for item in action.projects:
            project_id = legacy_project_id(actor, item.legacy_id)
            if db.exec(select(ChatProject.id).where(ChatProject.id == project_id)).first() is not None:
                results.append({"kind": "project", "legacy_id": item.legacy_id, "status": "already_imported"})
                continue
            owned, skipped = [], []
            for chat_id in dict.fromkeys(by_project.get(item.legacy_id, [])):
                if not cls.owned_conversation(sessions.get(chat_id), actor):
                    skipped.append((chat_id, "conversation_unavailable"))
                elif chat_id in assigned:
                    skipped.append((chat_id, "cloud_membership_kept"))
                else:
                    owned.append(chat_id)
            if not owned:
                results.append({"kind": "project", "legacy_id": item.legacy_id, "status": "not_owned"})
                continue
            created_at = None
            if item.created_at:
                try:
                    created_at = datetime.fromisoformat(item.created_at.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    created_at = None
            row = ChatProject(id=project_id, tenant_id=actor.tenant_id, user_id=actor.user_id, name=item.name)
            if created_at:
                row.created_at = created_at
            db.add(row)
            for chat_id in owned:
                db.add(
                    ChatProjectMembership(
                        tenant_id=actor.tenant_id, user_id=actor.user_id, chat_id=chat_id, project_id=project_id
                    )
                )
                assigned.add(chat_id)
            results.append(
                {"kind": "project", "legacy_id": item.legacy_id, "status": "imported", "project_id": project_id}
            )
            results.extend({"kind": "membership", "chat_id": c, "status": s} for c, s in skipped)
        db.flush()
        return {"items": results}

    @classmethod
    def snapshot(cls, actor: ProjectActor) -> dict:
        def operation(db):
            projects = db.exec(
                select(ChatProject)
                .where(ChatProject.user_id == actor.user_id, col(ChatProject.deleted_at).is_(None))
                .order_by(ChatProject.created_at, ChatProject.id)
            ).all()
            memberships = db.exec(
                select(ChatProjectMembership)
                .join(ChatProject, ChatProject.id == ChatProjectMembership.project_id)
                .join(MessageSession, MessageSession.chat_id == ChatProjectMembership.chat_id)
                .where(
                    ChatProjectMembership.user_id == actor.user_id,
                    ChatProject.user_id == actor.user_id,
                    col(ChatProject.deleted_at).is_(None),
                    MessageSession.user_id == actor.user_id,
                    col(MessageSession.api_subject_type).is_(None),
                    MessageSession.is_delete == False,  # noqa: E712 -- DM8 rejects IS 0
                )
                .order_by(ChatProjectMembership.chat_id)
            ).all()
            return {
                "identity": {"user_id": actor.user_id, "tenant_id": actor.tenant_id},
                "projects": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "created_at": r.created_at.isoformat(),
                        "updated_at": r.updated_at.isoformat(),
                    }
                    for r in projects
                ],
                "memberships": [{"chat_id": r.chat_id, "project_id": r.project_id} for r in memberships],
            }

        return cls.transaction(actor, operation)

    @classmethod
    def conversations(cls, actor, *, project_id=None, query="", cursor=None, limit=40):
        if not 1 <= limit <= 100 or (project_id is None and not query.strip()) or len(query) > 255:
            raise ProjectInputError()
        offset = decode_offset(cursor)

        def operation(db):
            if project_id:
                cls.project(db, actor, project_id)
            statement = (
                select(MessageSession)
                .join(ChatProjectMembership, ChatProjectMembership.chat_id == MessageSession.chat_id)
                .join(ChatProject, ChatProject.id == ChatProjectMembership.project_id)
                .where(
                    ChatProjectMembership.user_id == actor.user_id,
                    ChatProject.user_id == actor.user_id,
                    MessageSession.user_id == actor.user_id,
                    col(MessageSession.api_subject_type).is_(None),
                    MessageSession.is_delete == False,  # noqa: E712 -- DM8 rejects IS 0
                    col(ChatProject.deleted_at).is_(None),
                )
            )
            if project_id:
                statement = statement.where(ChatProject.id == str(project_id))
            if query.strip():
                escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                statement = statement.where(col(MessageSession.name).ilike(f"%{escaped}%", escape="\\"))
            # Immutable creation order keeps offset pagination stable across message touches.
            total = db.exec(statement.with_only_columns(func.count(MessageSession.chat_id))).one()
            rows = db.exec(
                statement.order_by(col(MessageSession.create_time).desc(), col(MessageSession.chat_id).desc())
                .offset(offset)
                .limit(limit + 1)
            ).all()
            from bisheng.workstation.domain.schemas.workstation_schema import WorkstationConversation

            data = [
                {
                    **WorkstationConversation.from_chat_session(row).model_dump(mode="json"),
                    "chat_id": row.chat_id,
                    "name": row.name,
                    "flow_id": row.flow_id,
                    "flow_type": row.flow_type,
                    "flow_name": row.flow_name,
                    "create_time": row.create_time.isoformat(),
                    "update_time": row.update_time.isoformat(),
                }
                for row in rows[:limit]
            ]
            return {
                "data": data,
                "total": total,
                "next_cursor": str(offset + limit) if len(rows) > limit else None,
            }

        return cls.transaction(actor, operation)
