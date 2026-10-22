"""Keep workflow file ownership independently of deletable question messages."""

import hashlib
import json
from collections.abc import Callable
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from sqlmodel import select, update

from bisheng.chat_session.domain.models.workflow_file_manifest import WorkflowFileManifest
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.database.models.message import ChatMessage
from bisheng.database.models.session import MessageSession

_SIGNATURE_PARAMS = frozenset(
    {
        "x-amz-algorithm",
        "x-amz-credential",
        "x-amz-date",
        "x-amz-expires",
        "x-amz-signedheaders",
        "x-amz-signature",
        "x-amz-security-token",
    }
)


def source_identity(value: str, *, storage_host: str = "", buckets: tuple[str, ...] = ()) -> str:
    """Only our own storage URLs may discard their host and signature fields."""
    parsed = urlsplit(value)
    bucket = parsed.path.lstrip("/").split("/", 1)[0]
    host = urlsplit(storage_host).netloc
    if bucket in buckets and (not parsed.netloc or (host and parsed.netloc.lower() == host.lower())):
        query = [
            (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in _SIGNATURE_PARAMS
        ]
        return json.dumps(["minio", unquote(parsed.path), query], separators=(",", ":"))
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path, parsed.query, ""))


class WorkflowFileRepository:
    @staticmethod
    def conversation_tenant(chat_id: str, user_id: int, workflow_id: str) -> int:
        with get_sync_db_session() as session:
            owner = session.exec(
                select(MessageSession).where(
                    MessageSession.chat_id == chat_id,
                    MessageSession.user_id == user_id,
                    MessageSession.flow_id == workflow_id,
                )
            ).first()
            if owner is None or owner.is_delete:
                raise ValueError("workflow attachment conversation is unavailable")
            return owner.tenant_id

    @staticmethod
    def save_assets(
        *,
        chat_id: str,
        user_id: int,
        workflow_id: str,
        source: dict,
        assets: list[dict],
        promote_source: Callable[[dict], None] | None = None,
        normalize_source: Callable[[str], str] = source_identity,
    ) -> None:
        with get_sync_db_session() as session:
            owner = session.exec(
                select(MessageSession)
                .where(
                    MessageSession.chat_id == chat_id,
                    MessageSession.user_id == user_id,
                    MessageSession.flow_id == workflow_id,
                )
                .with_for_update()
            ).first()
            if owner is None or owner.is_delete:
                raise ValueError("workflow attachment conversation is unavailable")
            target = normalize_source(source["file_url"])
            manifest_id = hashlib.sha256(
                json.dumps([owner.tenant_id, chat_id, user_id, source.get("file_id") or target]).encode()
            ).hexdigest()
            manifest = session.get(WorkflowFileManifest, manifest_id)
            messages = session.exec(
                select(ChatMessage)
                .where(
                    ChatMessage.chat_id == chat_id,
                    ChatMessage.user_id == user_id,
                    ChatMessage.category == "question",
                )
                .order_by(ChatMessage.id.desc())
                .with_for_update()
            ).all()
            matched_message = None
            files = []
            attachment = None
            for message in messages:
                candidate_files = json.loads(message.files or "[]")
                for candidate in candidate_files:
                    if not isinstance(candidate, dict):
                        continue
                    reference = candidate.get("filepath") or candidate.get("file_path") or candidate.get("file_url")
                    if normalize_source(reference or "") == target:
                        matched_message, files, attachment = message, candidate_files, candidate
                        break
                if attachment is not None:
                    break
            if attachment is None:
                if manifest is not None:
                    # A question may be deleted while its upload is in progress.
                    attachment = json.loads(manifest.files)[0]
                elif messages:
                    # Legacy form submissions sometimes only saved URLs in question text.
                    matched_message = messages[0]
                    files = json.loads(matched_message.files or "[]")
                    attachment = dict(source)
                    files.append(attachment)
                else:
                    raise ValueError("workflow source question has not been saved")
            if promote_source and not attachment.get("object_name"):
                promote_source(attachment)
            previous = {
                item["file_id"]: item
                for item in (attachment.get("derived_assets") or [])
                if isinstance(item, dict) and item.get("file_id")
            }
            previous.update({item["file_id"]: item for item in assets})
            attachment["derived_assets"] = list(previous.values())
            if matched_message is not None:
                matched_message.files = json.dumps(files, ensure_ascii=False)
                session.add(matched_message)
            # Each attempt holds its own images and retained source. This row
            # survives message deletion and preserves historical image access.
            retained = {**attachment, "derived_assets": assets}
            if manifest is None:
                manifest = WorkflowFileManifest(
                    id=manifest_id, tenant_id=owner.tenant_id, user_id=user_id, chat_id=chat_id, files="[]"
                )
            manifest.files = json.dumps([retained], ensure_ascii=False)
            session.add(manifest)
            session.commit()

    @staticmethod
    async def soft_delete_owned_session(chat_id: str, *, user_id: int, tenant_id: int) -> None:
        async with get_async_db_session() as session:
            await session.exec(
                update(MessageSession)
                .where(
                    MessageSession.chat_id == chat_id,
                    MessageSession.user_id == user_id,
                    MessageSession.tenant_id == tenant_id,
                    MessageSession.api_subject_type.is_(None),
                )
                .values(is_delete=True)
            )
            await session.commit()

    @staticmethod
    async def attachment_messages(chat_id: str) -> list[ChatMessage | WorkflowFileManifest]:
        """Read all legacy attachments and independent manifests using keysets."""
        messages = []
        async with get_async_db_session() as session:
            for model in (ChatMessage, WorkflowFileManifest):
                after = None
                while True:
                    statement = select(model).where(model.chat_id == chat_id, model.files.is_not(None))
                    if after is not None:
                        statement = statement.where(model.id > after)
                    result = await session.exec(statement.order_by(model.id.asc()).limit(500))
                    page = list(result.all())
                    messages.extend(page)
                    if len(page) < 500:
                        break
                    after = page[-1].id
        return messages
