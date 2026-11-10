"""Short, account-serialized SQL transactions; no network effects under locks."""

import base64
import hashlib
import json
from datetime import datetime

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from bisheng.chat_session.domain.models.project import (
    ChatProject,
    ChatProjectMembership,
    ChatProjectReceipt,
    ChatProjectRevision,
)
from bisheng.chat_session.domain.schemas.projects import ImportProjects, ProjectAction, ProjectActor
from bisheng.common.errcode.chat import (
    ProjectConversationError,
    ProjectInputError,
    ProjectRequestConflictError,
    ProjectSnapshotChangedError,
    ProjectUnavailableError,
)
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.core.database import get_sync_db_session
from bisheng.core.database.retry import retry_on_transient_db_conflict
from bisheng.database.models.session import MessageSession


def request_digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def encode_cursor(value: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode()


def decode_cursor(value: str | None, actor: ProjectActor, revision: int, kind: str) -> dict:
    if value is None:
        return {}
    try:
        if len(value) > 2048:
            raise ValueError("cursor too long")
        data = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if (
            not isinstance(data, dict)
            or data.get("actor") != [actor.tenant_id, actor.user_id]
            or data.get("kind") != kind
        ):
            raise ValueError("cursor scope mismatch")
        if data.get("revision") != str(revision):
            raise ProjectSnapshotChangedError()
        return data
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ProjectInputError() from exc


class ProjectRepository:
    @staticmethod
    def clock(db, actor: ProjectActor) -> ChatProjectRevision:
        row = db.exec(
            select(ChatProjectRevision).where(ChatProjectRevision.user_id == actor.user_id).with_for_update()
        ).first()
        if row is None:
            row = ChatProjectRevision(tenant_id=actor.tenant_id, user_id=actor.user_id)
            db.add(row)
            db.flush()
        if row.tenant_id != actor.tenant_id:
            # A missing tenant hook must fail closed, including in admin scopes.
            raise ProjectUnavailableError()
        return row

    @staticmethod
    @retry_on_transient_db_conflict()
    def transaction(actor: ProjectActor, operation):
        # Initial revision-row insertion can race. Roll back the entire unit,
        # then re-read under the database lock; no side effect has escaped.
        for attempt in range(4):
            try:
                with tenant_execution_scope(actor.tenant_id), get_sync_db_session() as db:
                    clock = ProjectRepository.clock(db, actor)
                    result = operation(db, clock)
                    db.commit()
                    return result
            except IntegrityError:
                if attempt == 3:
                    raise
                logger.warning("project-sync revision/receipt insertion conflict; retry={}", attempt + 1)

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
    def conversation(db, actor, chat_id, *, include_deleted=False):
        row = db.exec(select(MessageSession).where(MessageSession.chat_id == chat_id).with_for_update()).first()
        if (
            row is None
            or row.user_id != actor.user_id
            or row.tenant_id != actor.tenant_id
            or row.api_subject_type is not None
            or (row.is_delete and not include_deleted)
        ):
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

    @staticmethod
    def receipt(db, actor, key):
        row = db.exec(
            select(ChatProjectReceipt).where(ChatProjectReceipt.user_id == actor.user_id, ChatProjectReceipt.key == key)
        ).first()
        if row is not None and row.tenant_id != actor.tenant_id:
            raise ProjectUnavailableError()
        return row

    @staticmethod
    def save_receipt(db, actor, key, operation, digest, result, revision):
        db.add(
            ChatProjectReceipt(
                tenant_id=actor.tenant_id,
                user_id=actor.user_id,
                key=key,
                operation=operation,
                digest=digest,
                result=result,
                applied_revision=revision,
            )
        )

    @classmethod
    def execute(cls, actor: ProjectActor, action: ProjectAction) -> dict:
        payload = action.model_dump(mode="json", exclude={"request_id"})
        digest = request_digest(payload)
        key = f"mutation:{action.request_id}"

        def operation(db, clock):
            receipt = cls.receipt(db, actor, key)
            if receipt:
                if receipt.digest != digest:
                    raise ProjectRequestConflictError()
                return {
                    "applied_revision": str(receipt.applied_revision),
                    "revision": str(clock.revision),
                    "replayed": True,
                    "outcome": receipt.result,
                }
            if action.operation == "import":
                outcome = cls.import_batch(db, actor, action, clock.revision + 1)
            elif action.operation == "create":
                row = ChatProject(tenant_id=actor.tenant_id, user_id=actor.user_id, name=action.name)
                db.add(row)
                db.flush()
                if action.chat_id:
                    cls.assign(db, actor, action.chat_id, row.id)
                outcome = {"project_id": row.id}
            elif action.operation == "rename":
                row = cls.project(db, actor, action.project_id)
                row.name, row.updated_at = action.name, datetime.now()
                db.add(row)
                outcome = {"project_id": row.id}
            elif action.operation == "delete":
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
                outcome = {"project_id": row.id}
            else:
                cls.assign(db, actor, action.chat_id, action.project_id)
                outcome = {
                    "chat_id": action.chat_id,
                    "project_id": str(action.project_id) if action.project_id else None,
                }
            clock.revision += 1
            db.add(clock)
            cls.save_receipt(db, actor, key, action.operation, digest, outcome, clock.revision)
            return {
                "applied_revision": str(clock.revision),
                "revision": str(clock.revision),
                "replayed": False,
                "outcome": outcome,
            }

        return cls.transaction(actor, operation)

    @classmethod
    def import_batch(cls, db, actor, action: ImportProjects, revision):
        results = []

        def entry_key(kind, identity):
            return f"import-{kind}:" + request_digest([str(action.source_client_id), identity])

        for item in action.projects:
            key = entry_key("project", item.legacy_id)
            old = cls.receipt(db, actor, key)
            if old:
                results.append({"kind": "project", "legacy_id": item.legacy_id, **old.result, "replayed": True})
                continue
            row = ChatProject(tenant_id=actor.tenant_id, user_id=actor.user_id, name=item.name)
            if item.created_at:
                try:
                    row.created_at = datetime.fromisoformat(item.created_at.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    results.append({"kind": "project", "legacy_id": item.legacy_id, "status": "invalid_date"})
                    continue
            db.add(row)
            result = {"project_id": row.id, "status": "imported"}
            cls.save_receipt(db, actor, key, "import-project", "", result, revision)
            db.flush()
            results.append({"kind": "project", "legacy_id": item.legacy_id, **result})
        for item in action.memberships:
            # One source conversation gets one import attempt, even if a later
            # batch changes its legacy project. User cloud edits always win.
            key = entry_key("member", item.chat_id)
            old = cls.receipt(db, actor, key)
            if old:
                results.append({"kind": "membership", "chat_id": item.chat_id, **old.result, "replayed": True})
                continue
            mapping = cls.receipt(db, actor, entry_key("project", item.legacy_project_id))
            result = {"status": "project_unavailable"}
            if mapping:
                try:
                    cls.project(db, actor, mapping.result["project_id"])
                    cls.conversation(db, actor, item.chat_id)
                    if cls.membership(db, actor, item.chat_id):
                        result = {"status": "cloud_membership_kept"}
                    else:
                        cls.assign(db, actor, item.chat_id, mapping.result["project_id"])
                        result = {"status": "imported", "project_id": mapping.result["project_id"]}
                except ProjectUnavailableError:
                    result = {"status": "project_unavailable"}
                except ProjectConversationError:
                    result = {"status": "conversation_unavailable"}
            cls.save_receipt(db, actor, key, "import-member", "", result, revision)
            db.flush()
            results.append({"kind": "membership", "chat_id": item.chat_id, **result})
        return {"items": results}

    @classmethod
    def snapshot(cls, actor: ProjectActor, cursor=None, limit=500):
        if not 1 <= limit <= 500:
            raise ProjectInputError()

        def operation(db, clock):
            state = decode_cursor(cursor, actor, clock.revision, "snapshot")
            stage, last = state.get("stage", "projects"), state.get("last", "")
            if stage not in ("projects", "memberships") or not isinstance(last, str):
                raise ProjectInputError()
            projects, memberships, next_state = [], [], None
            if stage == "projects":
                rows = db.exec(
                    select(ChatProject)
                    .where(
                        ChatProject.user_id == actor.user_id,
                        col(ChatProject.deleted_at).is_(None),
                        ChatProject.id > last,
                    )
                    .order_by(ChatProject.id)
                    .limit(limit + 1)
                ).all()
                projects = [
                    {
                        "id": r.id,
                        "name": r.name,
                        "created_at": r.created_at.isoformat(),
                        "updated_at": r.updated_at.isoformat(),
                    }
                    for r in rows[:limit]
                ]
                if len(rows) > limit:
                    next_state = {"stage": "projects", "last": rows[limit - 1].id}
                else:
                    stage, last = "memberships", ""
            if stage == "memberships":
                remaining = limit - len(projects)
                rows = db.exec(
                    select(ChatProjectMembership)
                    .join(ChatProject, ChatProject.id == ChatProjectMembership.project_id)
                    .join(MessageSession, MessageSession.chat_id == ChatProjectMembership.chat_id)
                    .where(
                        ChatProjectMembership.user_id == actor.user_id,
                        ChatProject.user_id == actor.user_id,
                        col(ChatProject.deleted_at).is_(None),
                        MessageSession.user_id == actor.user_id,
                        col(MessageSession.api_subject_type).is_(None),
                        MessageSession.is_delete == False,  # noqa: E712
                        ChatProjectMembership.chat_id > last,
                    )
                    .order_by(ChatProjectMembership.chat_id)
                    .limit(remaining + 1)
                ).all()
                memberships = [{"chat_id": r.chat_id, "project_id": r.project_id} for r in rows[:remaining]]
                if len(rows) > remaining:
                    next_state = {"stage": "memberships", "last": rows[remaining - 1].chat_id if remaining else last}
            base = {"actor": [actor.tenant_id, actor.user_id], "revision": str(clock.revision), "kind": "snapshot"}
            return {
                "protocol_version": 1,
                "identity": {"user_id": actor.user_id, "tenant_id": actor.tenant_id},
                "revision": str(clock.revision),
                "projects": projects,
                "memberships": memberships,
                "next_cursor": encode_cursor({**base, **next_state}) if next_state else None,
            }

        return cls.transaction(actor, operation)

    @classmethod
    def version(cls, actor):
        return cls.transaction(actor, lambda db, clock: str(clock.revision))

    @classmethod
    def conversations(cls, actor, *, project_id=None, query="", cursor=None, limit=40):
        if not 1 <= limit <= 100 or (project_id is None and not query.strip()) or len(query) > 255:
            raise ProjectInputError()
        kind = "conversations:" + request_digest([project_id, query])

        def operation(db, clock):
            state = decode_cursor(cursor, actor, clock.revision, kind)
            offset = state.get("offset", 0)
            if type(offset) is not int or offset < 0:
                raise ProjectInputError()
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
            # Immutable creation order keeps pagination stable across message touches.
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
            more = len(rows) > limit
            next_cursor = (
                encode_cursor(
                    {
                        "actor": [actor.tenant_id, actor.user_id],
                        "revision": str(clock.revision),
                        "kind": kind,
                        "offset": offset + limit,
                    }
                )
                if more
                else None
            )
            return {
                "data": data,
                "total": total,
                "revision": str(clock.revision),
                "next_cursor": next_cursor,
            }

        return cls.transaction(actor, operation)
