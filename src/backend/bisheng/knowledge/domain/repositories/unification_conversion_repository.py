"""Bounded SQL conversion facts and writes; the caller owns durable commit."""

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from weakref import WeakKeyDictionary

from sqlalchemy import Integer, String, and_, case, cast, delete, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from bisheng.knowledge.domain.repositories import unification_resource_repository as raw
from bisheng.knowledge.domain.repositories.unification_inventory_repository import DefaultRow
from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository
from bisheng.knowledge.domain.repositories.unification_space_membership_repository import (
    UnificationSpaceMembershipRepository,
    _current,
)
from bisheng.knowledge.domain.schemas.unification_conversion import (
    DefaultConversionCommand,
    InitializeV1Command,
    ResourceConversionCommand,
    TagConversionCommand,
    TagLinkConversionCommand,
    initial_version_templates,
)
from bisheng.knowledge.domain.services.unification_fingerprints import canonical, digest
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig as Default
from bisheng.llm.domain.services.chat_default_model_backfill import transform_chat_default
from bisheng.llm.domain.services.linsight_default_model_backfill import transform_linsight_llm_config
from bisheng.resource_reference.application.contracts import TransactionIdentity

KINDS = {
    ResourceConversionCommand: "resource_conversion",
    InitializeV1Command: "initialize_v1",
    TagConversionCommand: "tag_conversion",
    TagLinkConversionCommand: "tag_link_conversion",
    DefaultConversionCommand: "default_conversion",
}
DEFAULT_COLUMNS = tuple(DefaultRow.__dataclass_fields__)
RESOURCE_PROJECTION = raw.RESOURCE_COLUMNS + raw.NEUTRAL_COLUMNS


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="migration_conversion_" + reason)


def _hash(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _clean(session):
    raw._scope(session)
    if session.new or session.dirty or session.deleted:
        _blocked("pending_caller_writes")


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class LockedConversionScope:
    run_id: str
    writer_contract_version: str
    tenant_id: int
    baseline_hash: str
    plan_hash: str
    commands_digest: str


@dataclass(frozen=True, slots=True)
class ConversionOutcome:
    command_key: str
    operation: str
    actual_after_digest: str
    document_id: int | None = None
    version_id: int | None = None


class UnificationConversionRepository:
    def __init__(self):
        self._scopes = WeakKeyDictionary()
        self.runs = KnowledgeUnificationRunRepository()
        self.members = UnificationSpaceMembershipRepository()

    async def _read(self, session, query):
        tenant, transaction = raw._scope(session), TransactionIdentity.capture(session)
        _current(session, tenant, transaction)
        with session.no_autoflush, strict_tenant_filter():
            rows = tuple((await session.execute(query)).mappings())
        _current(session, tenant, transaction)
        return rows

    async def aread_run(self, session, *, run_id, writer_contract_version, lock=False):
        """Read detached scalar facts without refreshing the caller's ORM row."""
        self.runs._identity(run_id, writer_contract_version)
        query = select(Run.__table__).where(Run.run_id == run_id, Run.tenant_id == raw._scope(session))
        rows = await self._read(session, query.with_for_update() if lock else query)
        if not rows:
            _blocked("run_missing")
        run = Run(**dict(rows[0]))
        self.runs._validate(run, run_id, writer_contract_version)
        return run

    async def _rows(self, session, model, columns, ids, *, lock=True):
        ids = tuple(sorted(set(ids)))
        rows = {}
        for start in range(0, len(ids), 200):
            table = model.__table__
            query = (
                select(*(table.c[name] for name in columns))
                .where(table.c.id.in_(ids[start : start + 200]))
                .order_by(table.c.id)
            )
            if lock:
                query = query.with_for_update()
            rows.update((row["id"], raw._values(row, columns)) for row in await self._read(session, query))
        return rows

    def _bound(self, session, scope):
        value = self._scopes.get(scope) if type(scope) is LockedConversionScope else None
        if value is None or value["seal"] != digest(asdict(scope)):
            _blocked("unsigned_scope")
        try:
            original = value["transaction"]
            active = value.get("owned_savepoint", original)
            active.assert_current(session)
            if active is not original and (
                active.transaction.parent is not original.transaction or not original.transaction.is_active
            ):
                _blocked("original_transaction_changed")
        except (ValueError, TypeError):
            _blocked("original_transaction_changed")
        if (
            raw._scope(session) != scope.tenant_id
            or digest([asdict(cmd) for cmd in value["commands"]]) != scope.commands_digest
        ):
            _blocked("scope_changed")
        return value

    async def alock_scope(
        self, session, *, run_id, writer_contract_version, baseline_hash, plan_hash, commands, verification=False
    ):
        _clean(session)
        tenant = raw._scope(session)
        transaction = TransactionIdentity.capture(session)

        def current():
            _current(session, tenant, transaction)

        if type(commands) is not tuple or len(commands) > 200:
            _blocked("invalid_batch")
        for cmd in commands:
            if (
                type(cmd) not in KINDS
                or type(cmd.schema_version) is not int
                or type(cmd.tenant_id) is not int
                or (
                    cmd.schema_version,
                    cmd.run_id,
                    cmd.writer_contract_version,
                    cmd.tenant_id,
                    cmd.operation,
                )
                != (1, run_id, writer_contract_version, tenant, KINDS[type(cmd)])
            ):
                _blocked("invalid_command")
            if not _hash(cmd.command_key) or any(
                not _hash(value)
                for name, value in asdict(cmd).items()
                if name.endswith("_digest") and value is not None
            ):
                _blocked("invalid_fingerprint")
            if any(
                type(value) is not int or value <= 0
                for name, value in asdict(cmd).items()
                if name in {"knowledge_id", "file_id", "tag_id", "link_id", "row_id", "survivor_link_id"}
            ):
                _blocked("invalid_identifier")
            if type(cmd) is DefaultConversionCommand and cmd.algorithm_version != "sql-default-conversion-v1":
                _blocked("unknown_default_algorithm")
            if type(cmd) is InitializeV1Command and (
                type(cmd.planned_at) is not datetime or cmd.planned_at.microsecond or cmd.planned_at.tzinfo is not None
            ):
                _blocked("unrepresentable_planned_time")
        if len({cmd.command_key for cmd in commands}) != len(commands):
            _blocked("duplicate_command")
        run = await self.aread_run(session, run_id=run_id, writer_contract_version=writer_contract_version, lock=True)
        current()
        self._verification_phase(run, baseline_hash, plan_hash, verification)
        value = await self._load(session, commands, False, current=current)
        current()
        scope = LockedConversionScope(
            run_id, writer_contract_version, tenant, baseline_hash, plan_hash, digest([asdict(cmd) for cmd in commands])
        )
        value.update(
            commands=commands,
            transaction=transaction,
            seal=digest(asdict(scope)),
            checkpoint=digest(run.checkpoints.get("converting", {}).get("sql_conversion")),
            verification=verification,
        )
        self._scopes[scope] = value
        self._parents(scope, value)
        return scope

    async def _load(self, session, commands, root_values=True, *, current):
        resources = {cmd.knowledge_id for cmd in commands if type(cmd) is ResourceConversionCommand}
        roots = {cmd.knowledge_id for cmd in commands if hasattr(cmd, "knowledge_id")}
        root_rows = await self._rows(session, Knowledge, ("id", "tenant_id", "type", "user_id"), roots)
        if root_values:
            root_rows.update(await self._rows(session, Knowledge, RESOURCE_PROJECTION, resources))
        members = await self.members._alock_conversion_sets(
            session, roots=root_rows, commands=commands, current=current
        )
        file_ids = {cmd.file_id for cmd in commands if hasattr(cmd, "file_id")}
        version_ids = set()
        for start in range(0, len(file_ids), 200):
            counts = await self._read(
                session,
                select(Version.knowledge_file_id, func.count().label("count"), func.min(Version.id).label("id"))
                .where(Version.knowledge_file_id.in_(sorted(file_ids)[start : start + 200]))
                .group_by(Version.knowledge_file_id),
            )
            if any(row["count"] != 1 for row in counts):
                _blocked("multiple_file_versions")
            version_ids.update(row["id"] for row in counts)
        discovered = await self._rows(session, Version, ("id", "document_id"), version_ids, lock=False)
        doc_ids = {row["document_id"] for row in discovered.values()}
        headers = await self._rows(session, Document, ("id", "primary_version_id"), doc_ids, lock=False)
        primary_ids = {row["primary_version_id"] for row in headers.values() if row["primary_version_id"] is not None}
        primary_headers = await self._rows(session, Version, ("id", "knowledge_file_id"), primary_ids, lock=False)
        primary_file_ids = {row["knowledge_file_id"] for row in primary_headers.values()}
        primary_files = await self._rows(
            session, File, ("id", "tenant_id", "knowledge_id", "file_type"), file_ids | primary_file_ids
        )
        files = await self._rows(session, File, raw.FILE_COLUMNS, file_ids)
        documents = await self._rows(session, Document, raw.DOCUMENT_COLUMNS, doc_ids)
        all_versions = await self._rows(session, Version, raw.VERSION_COLUMNS, version_ids | primary_ids)
        versions = {key: row for key, row in all_versions.items() if key in version_ids}
        primaries = {key: row for key, row in all_versions.items() if key in primary_ids}
        v1_files = {cmd.file_id for cmd in commands if type(cmd) is InitializeV1Command}
        v1_docs = {row["document_id"] for row in versions.values() if row["knowledge_file_id"] in v1_files}
        v1_counts = {}
        if v1_docs:
            for row in await self._read(
                session,
                select(Version.document_id, func.count().label("count"))
                .where(Version.document_id.in_(v1_docs))
                .group_by(Version.document_id),
            ):
                v1_counts[row["document_id"]] = row["count"]
        await self._tag_relations(session, commands)
        tags = await self._rows(
            session, Tag, raw.TAG_COLUMNS, [cmd.tag_id for cmd in commands if hasattr(cmd, "tag_id")]
        )
        links = await self._rows(
            session,
            TagLink,
            raw.LINK_COLUMNS,
            [
                ident
                for cmd in commands
                if type(cmd) is TagLinkConversionCommand
                for ident in (cmd.link_id, cmd.survivor_link_id)
            ],
        )
        defaults = await self._rows(
            session, Default, DEFAULT_COLUMNS, [cmd.row_id for cmd in commands if type(cmd) is DefaultConversionCommand]
        )
        return {
            "members": members,
            "roots": root_rows,
            "files": files,
            "documents": documents,
            "versions": versions,
            "versions_by_file": {row["knowledge_file_id"]: row for row in versions.values()},
            "primaries": primaries,
            "primary_files": primary_files,
            "v1_counts": v1_counts,
            "tags": tags,
            "links": links,
            "defaults": defaults,
        }

    async def _tag_relations(self, session, commands):
        ids = [cmd.tag_id for cmd in commands if type(cmd) is TagConversionCommand]
        if not ids:
            return
        tag, link, file = (
            Tag.__table__.alias("conversion_tag"),
            TagLink.__table__.alias("conversion_link"),
            File.__table__.alias("conversion_file"),
        )
        file_id = case((link.c.resource_type.in_((8, 9)), cast(link.c.resource_id, Integer)), else_=None)
        bad = or_(
            link.c.resource_type.not_in((8, 9)),
            link.c.tenant_id.is_(None),
            link.c.tenant_id != tag.c.tenant_id,
            file.c.id.is_(None),
            file.c.tenant_id != tag.c.tenant_id,
            file.c.file_type != 1,
            cast(file.c.id, String) != link.c.resource_id,
            cast(file.c.knowledge_id, String) != tag.c.business_id,
        )
        query = (
            select(link.c.id)
            .join(tag, tag.c.id == link.c.tag_id)
            .outerjoin(file, file.c.id == file_id)
            .where(tag.c.id.in_(ids), bad)
            .limit(1)
        )
        other = Tag.__table__.alias("conversion_other_tag")
        collision = (
            select(tag.c.id)
            .join(
                other,
                and_(
                    other.c.tenant_id == tag.c.tenant_id,
                    other.c.id != tag.c.id,
                    other.c.business_id == tag.c.business_id,
                    other.c.name == tag.c.name,
                    other.c.business_type == "knowledge_space",
                ),
            )
            .where(tag.c.id.in_(ids))
            .limit(1)
        )
        if await self._read(session, query) or await self._read(session, collision):
            _blocked("tag_relationship_changed")

    def _parents(self, scope, value):
        for rows in value.values():
            if type(rows) is dict:
                for row in rows.values():
                    if type(row) is dict and "tenant_id" in row and row["tenant_id"] != scope.tenant_id:
                        _blocked("foreign_row")
        for cmd in value["commands"]:
            if hasattr(cmd, "knowledge_id"):
                root = value["roots"].get(cmd.knowledge_id)
                if root is None or root["type"] not in (0, 3):
                    _blocked("root_missing_or_kind")
            if hasattr(cmd, "file_id"):
                file = value["files"].get(cmd.file_id)
                if file is None or file["file_type"] != 1 or file["knowledge_id"] != cmd.knowledge_id:
                    _blocked("file_parent_invalid")
            if hasattr(cmd, "tag_id"):
                tag = value["tags"].get(cmd.tag_id)
                if (
                    tag is None
                    or tag["business_id"] != str(cmd.knowledge_id)
                    or tag["business_type"] not in {"knowledge", "knowledge_space"}
                ):
                    _blocked("tag_parent_invalid")
            if type(cmd) is DefaultConversionCommand:
                row = value["defaults"].get(cmd.row_id)
                if row is None or row["key"] != "linsight_llm" or cmd.key != row["key"]:
                    _blocked("default_parent_invalid")
        for version in value["versions"].values():
            doc, file = value["documents"].get(version["document_id"]), value["files"].get(version["knowledge_file_id"])
            if doc is None or file is None or doc["knowledge_id"] != file["knowledge_id"]:
                _blocked("version_parent_invalid")
            primary = value["primaries"].get(doc["primary_version_id"])
            primary_file = value["primary_files"].get(primary["knowledge_file_id"]) if primary else None
            if (
                primary is None
                or primary["document_id"] != doc["id"]
                or not primary["is_primary"]
                or primary_file is None
                or primary_file["knowledge_id"] != doc["knowledge_id"]
                or primary_file["file_type"] != 1
                or version["version_no"] < 1
                or bool(version["is_primary"]) != (version["id"] == doc["primary_version_id"])
            ):
                _blocked("primary_chain_invalid")

    def _before(self, value):
        for cmd in value["commands"]:
            if type(cmd) is ResourceConversionCommand:
                row = value["roots"][cmd.knowledge_id]
                if (
                    (cmd.target_type, cmd.target_is_released, cmd.target_migration_origin) != (3, False, cmd.run_id)
                    or row["type"] != 0
                    or digest(raw._values(row, raw.RESOURCE_COLUMNS)) != cmd.before_business_digest
                    or digest(raw._values(row, raw.NEUTRAL_COLUMNS)) != cmd.before_neutral_digest
                ):
                    _blocked("resource_before_changed")
                self.members._assert_conversion_before(
                    command=cmd, root=row, members=value["members"][cmd.knowledge_id]
                )
            elif type(cmd) is InitializeV1Command:
                if (
                    digest(value["files"][cmd.file_id]) != cmd.file_business_digest
                    or cmd.file_id in value["versions_by_file"]
                    or cmd.before_relation_digest != digest(())
                ):
                    _blocked("file_before_changed")
                if (value["files"][cmd.file_id]["file_level_path"], value["files"][cmd.file_id]["level"]) != (
                    cmd.file_level_path,
                    cmd.level,
                ):
                    _blocked("file_template_scope_changed")
                self._templates(cmd)
            elif type(cmd) is TagConversionCommand:
                if (cmd.from_business_type, cmd.to_business_type) != ("knowledge", "knowledge_space") or digest(
                    value["tags"][cmd.tag_id]
                ) != cmd.before_digest:
                    _blocked("tag_before_changed")
            elif type(cmd) is TagLinkConversionCommand:
                row = value["links"].get(cmd.link_id)
                survivor = value["links"].get(cmd.survivor_link_id)
                if (
                    row is None
                    or digest(row) != cmd.before_digest
                    or (cmd.from_type, cmd.to_type) != (9, 8)
                    or row["resource_type"] != 9
                    or row["resource_id"] != str(cmd.file_id)
                    or row["tag_id"] != cmd.tag_id
                ):
                    _blocked("link_before_changed")
                if cmd.action == "drop_duplicate":
                    if (
                        cmd.after_digest is not None
                        or cmd.survivor_link_id == cmd.link_id
                        or survivor is None
                        or digest(survivor) != cmd.survivor_digest
                        or (survivor["resource_id"], survivor["resource_type"], survivor["tag_id"])
                        != (str(cmd.file_id), 8, cmd.tag_id)
                    ):
                        _blocked("survivor_before_changed")
                elif cmd.action != "retag" or cmd.survivor_link_id != cmd.link_id:
                    _blocked("invalid_link_action")
            else:
                row = value["defaults"][cmd.row_id]
                if digest(row) != cmd.before_raw_row_digest:
                    _blocked("default_before_changed")
                payload = json.loads(row["value"])
                after, _ = transform_linsight_llm_config(payload)
                after, _ = transform_chat_default(after)
                if (
                    digest({"key": row["key"], "value": payload}) != cmd.before_configuration_digest
                    or digest({"key": row["key"], "value": after}) != cmd.after_configuration_digest
                ):
                    _blocked("default_configuration_changed")

    @staticmethod
    def _templates(cmd):
        expected = digest(
            {
                "run_id": cmd.run_id,
                "writer_contract_version": cmd.writer_contract_version,
                "tenant_id": cmd.tenant_id,
                "file_id": cmd.file_id,
                "action": "register_v1",
            }
        )
        if cmd.natural_key != expected:
            _blocked("natural_key_changed")
        templates = initial_version_templates(
            knowledge_id=cmd.knowledge_id,
            file_id=cmd.file_id,
            file_level_path=cmd.file_level_path,
            level=cmd.level,
            planned_at=cmd.planned_at,
            natural_key=cmd.natural_key,
        )
        if tuple(map(digest, templates)) != (cmd.document_template_digest, cmd.version_template_digest):
            _blocked("template_changed")
        return templates

    def _verification_phase(self, run, baseline_hash, plan_hash, verification):
        self.runs._hashes(run, baseline_hash, plan_hash)
        if run.phase != "converting" and not (
            verification
            and run.phase in {"backfilling", "verifying", "verified", "completed"}
            and run.checkpoints.get("converting", {}).get("sql_conversion", {}).get("complete") is True
        ):
            _blocked("phase_changed")

    async def _current_run(self, session, scope, value):
        run = await self.aread_run(
            session, run_id=scope.run_id, writer_contract_version=scope.writer_contract_version, lock=True
        )
        self._verification_phase(run, scope.baseline_hash, scope.plan_hash, value["verification"])
        if digest(run.checkpoints.get("converting", {}).get("sql_conversion")) != value["checkpoint"]:
            _blocked("checkpoint_changed")

    async def aapply_and_read_after(self, session, *, scope):
        _clean(session)
        value = self._bound(session, scope)
        if value["verification"]:
            _blocked("verification_scope_cannot_write")

        def current():
            _current(session, scope.tenant_id, value.get("owned_savepoint", value["transaction"]))

        try:
            await self._current_run(session, scope, value)
            value.update(await self._load(session, value["commands"], current=current))
            self._parents(scope, value)
            self._before(value)
            async with session.begin_nested():
                value["owned_savepoint"] = TransactionIdentity.capture(session)
                for cmd in value["commands"]:
                    current()
                    if type(cmd) is ResourceConversionCommand:
                        await session.execute(
                            update(Knowledge.__table__)
                            .where(Knowledge.id == cmd.knowledge_id, Knowledge.tenant_id == scope.tenant_id)
                            .values(
                                type=3,
                                is_released=False,
                                migration_origin=scope.run_id,
                                update_time=value["roots"][cmd.knowledge_id]["update_time"],
                            )
                        )
                        member_id = await self.members._aapply_conversion_member(session, command=cmd, current=current)
                        value.setdefault("member_ids", {})[cmd.knowledge_id] = member_id
                    elif type(cmd) is TagConversionCommand:
                        await session.execute(
                            update(Tag.__table__)
                            .where(Tag.id == cmd.tag_id, Tag.tenant_id == scope.tenant_id)
                            .values(
                                business_type="knowledge_space", update_time=value["tags"][cmd.tag_id]["update_time"]
                            )
                        )
                        current()
                    elif type(cmd) is TagLinkConversionCommand:
                        statement = (
                            delete(TagLink.__table__)
                            if cmd.action == "drop_duplicate"
                            else update(TagLink.__table__).values(
                                resource_type=8, update_time=value["links"][cmd.link_id]["update_time"]
                            )
                        )
                        await session.execute(
                            statement.where(TagLink.id == cmd.link_id, TagLink.tenant_id == scope.tenant_id)
                        )
                        current()
                    elif type(cmd) is DefaultConversionCommand:
                        row = value["defaults"][cmd.row_id]
                        after, _ = transform_linsight_llm_config(json.loads(row["value"]))
                        after, _ = transform_chat_default(after)
                        await session.execute(
                            update(Default.__table__)
                            .where(Default.id == cmd.row_id, Default.tenant_id == scope.tenant_id)
                            .values(value=canonical(after).decode(), update_time=row["update_time"])
                        )
                        current()
                    else:
                        document, version = self._templates(cmd)
                        document.pop("primary_version_key")
                        version.pop("document_key")
                        doc = Document(**document)
                        session.add(doc)
                        current()
                        await session.flush()
                        current()
                        version = Version(document_id=doc.id, **version)
                        session.add(version)
                        current()
                        await session.flush()
                        current()
                        await session.execute(
                            update(Document.__table__)
                            .where(
                                Document.id == doc.id,
                                Document.knowledge_id.in_(
                                    select(Knowledge.id).where(Knowledge.tenant_id == scope.tenant_id)
                                ),
                            )
                            .values(primary_version_id=version.id, update_time=cmd.planned_at)
                        )
                        current()
                current()
                await session.flush()
                current()
                return await self.aread_after(session, scope=scope)
        except SQLAlchemyError as error:
            raise KnowledgeOperationPlanConflictError(reason="migration_conversion_sql_failed") from error
        finally:
            self._scopes.pop(scope, None)

    async def aread_after(self, session, *, scope):
        _clean(session)
        value = self._bound(session, scope)

        def current_guard():
            _current(session, scope.tenant_id, value.get("owned_savepoint", value["transaction"]))

        await self._current_run(session, scope, value)
        current = await self._load(session, value["commands"], current=current_guard)
        self._parents(scope, current | {"commands": value["commands"]})
        result = []
        for cmd in value["commands"]:
            doc_id = version_id = None
            if type(cmd) is ResourceConversionCommand:
                row = current["roots"][cmd.knowledge_id]
                hashes = (digest(raw._values(row, raw.RESOURCE_COLUMNS)), digest(raw._values(row, raw.NEUTRAL_COLUMNS)))
                if hashes != (cmd.after_business_digest, cmd.after_neutral_digest):
                    _blocked("resource_after_changed")
                member_id, member_digest = self.members._assert_conversion_after(
                    command=cmd,
                    root=row,
                    members=current["members"][cmd.knowledge_id],
                    expected_member_id=value.get("member_ids", {}).get(cmd.knowledge_id),
                )
                after = digest((*hashes, member_id, member_digest))
            elif type(cmd) is InitializeV1Command:
                self._templates(cmd)
                version = current["versions_by_file"].get(cmd.file_id)
                if (
                    version is None
                    or current["v1_counts"][version["document_id"]] != 1
                    or digest(current["files"][cmd.file_id]) != cmd.file_business_digest
                ):
                    _blocked("v1_after_invalid")
                doc = current["documents"][version["document_id"]]
                if doc["primary_version_id"] != version["id"]:
                    _blocked("v1_primary_invalid")
                document = raw._values(doc, raw.DOCUMENT_COLUMNS)
                actual_version = raw._values(version, raw.VERSION_COLUMNS)
                doc_id, version_id = document.pop("id"), actual_version.pop("id")
                document.pop("primary_version_id")
                actual_version.pop("document_id")
                document["primary_version_key"] = actual_version["document_key"] = cmd.natural_key
                if (digest(document), digest(actual_version)) != (
                    cmd.document_template_digest,
                    cmd.version_template_digest,
                ):
                    _blocked("v1_template_after_changed")
                after = digest((document, actual_version, doc_id, version_id))
            elif type(cmd) is TagConversionCommand:
                after = digest(current["tags"][cmd.tag_id])
                if after != cmd.after_digest:
                    _blocked("tag_after_changed")
            elif type(cmd) is TagLinkConversionCommand:
                row = current["links"].get(cmd.link_id)
                survivor = current["links"].get(cmd.survivor_link_id)
                if (
                    survivor is None
                    or digest(survivor) != cmd.survivor_digest
                    or (cmd.action == "drop_duplicate" and row is not None)
                    or (cmd.action == "retag" and (row is None or digest(row) != cmd.after_digest))
                ):
                    _blocked("link_after_changed")
                after = digest((row, survivor))
            else:
                row = current["defaults"][cmd.row_id]
                if (
                    digest(row) != cmd.after_business_revision_digest
                    or digest({"key": row["key"], "value": json.loads(row["value"])}) != cmd.after_configuration_digest
                ):
                    _blocked("default_after_changed")
                after = digest(row)
            result.append(ConversionOutcome(cmd.command_key, cmd.operation, after, doc_id, version_id))
        self._bound(session, scope)
        return tuple(result)
