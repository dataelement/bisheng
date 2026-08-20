import json
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any, ClassVar, Literal

# if TYPE_CHECKING:
from pydantic import field_validator
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, and_, case, cast, exists, or_, text
from sqlmodel import Field, col, delete, func, select, update

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.knowledge.domain.constants import parse_shougang_file_encoding_codes
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType
from bisheng.database.base import async_get_count, get_count


class KnowledgeFileStatus(int, Enum):
    PROCESSING = 1  # Sedang diproses
    SUCCESS = 2  # Berhasil
    FAILED = 3  # Parse Failure
    REBUILDING = 4  # Rebuilding
    WAITING = 5  # In queue:
    TIMEOUT = 6  # Super24Hour not parsed, parsing timeout
    VIOLATION = 7  # Content safety violation


MEMBER_HIDDEN_FILE_STATUSES = frozenset(
    {
        KnowledgeFileStatus.FAILED.value,  # 3 解析失败
        KnowledgeFileStatus.TIMEOUT.value,  # 6 解析超时
        KnowledgeFileStatus.VIOLATION.value,  # 7 违规
    }
)


class QAStatus(Enum):
    DISABLED = 0  # User manually closedQA
    ENABLED = 1  # Enabled
    PROCESSING = 2  # Sedang diproses
    FAILED = 3  # QAFailed to insert vector library


class ParseType(Enum):
    LOCAL = "local"  # Local mode resolution
    UNS = "uns"  # unsService resolution, all converted topdfDoc.

    # 1.3.0After the enumeration, the previous belongs to the file parsed on the version
    ETL4LM = "etl4lm"  # etl4lmService Insights, includingpdfLayout Analysis for
    UN_ETL4LM = "un_etl4lm"  # Nonetl4lmService parsing, nobboxContent, only source files andmdDoc.
    MINERU = "mineru"
    PADDLE_OCR = "paddle_ocr"


class FileSource(Enum):
    UPLOAD = "upload"  # user upload
    CHANNEL = "channel"
    SPACE_UPLOAD = "space_upload"
    AUDIO_TRANSCRIPT = "audio_transcript"
    VIDEO_TRANSCRIPT = "video_transcript"
    WEB_LINK = "web_link"


class KnowledgeFileEntryType(str, Enum):
    MANAGER = "manager"
    PUBLISH = "publish"
    SHARE = "share"
    PROJECTION_TOMBSTONE = "projection_tombstone"


class KnowledgeFileEntryStatus(str, Enum):
    PREPARING = "preparing"
    ACTIVE = "active"
    DELETING = "deleting"
    INVALID = "invalid"


class KnowledgeFileProjectionStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROJECTING = "processing"  # backwards-compatible alias
    READY = "ready"
    FAILED = "failed"


# Portal "my uploads" list: space uploads plus media reclassified at ingest time.
PORTAL_USER_UPLOAD_FILE_SOURCES = (
    FileSource.SPACE_UPLOAD.value,
    FileSource.AUDIO_TRANSCRIPT.value,
    FileSource.VIDEO_TRANSCRIPT.value,
)


class FileType(int, Enum):
    DIR = 0
    FILE = 1


class KnowledgeFileBase(SQLModelSerializable):
    user_id: int | None = Field(default=None, index=True)
    user_name: str | None = Field(default=None, index=True)
    knowledge_id: int = Field(index=True)
    thumbnails: str | None = Field(default=None, description="File thumbnails in Stored object name")
    file_name: str = Field(max_length=200, index=True)
    alias_name: str | None = Field(
        default=None,
        max_length=200,
        description="AI-generated display alias for the file; falls back to file_name when null",
    )
    file_type: int = Field(default=FileType.FILE.value, description="File type. 0: dir; 1: file")
    file_source: str | None = Field(default=FileSource.UPLOAD.value, description="File source")
    level: int | None = Field(default=0)
    file_level_path: str | None = Field(default=None, index=True)
    sort_weight: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=True,
            comment="管理员手动排序权重，越小越靠前；NULL 表示未排过，排在已排序的之后",
        ),
    )
    abstract: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    file_size: int | None = Field(default=None, index=False, description="File size inbytes")
    md5: str | None = Field(default=None, index=False)
    parse_type: str | None = Field(default=ParseType.LOCAL.value, index=False, description="Files parsed in what mode")
    parse_priority: str | None = Field(
        default=None,
        sa_column=Column(String(16), nullable=True),
        description="Immutable file parsing priority snapshot",
    )
    split_rule: str | None = Field(default=None, sa_column=Column(Text), description="Files parsed in what mode")
    preview_file_object_name: str | None = Field(default=None, index=True, description="Preview File Object name")
    bbox_object_name: str | None = Field(default="", description="bboxFiles inminioStored object name")
    status: int | None = Field(default=KnowledgeFileStatus.WAITING.value)
    object_name: str | None = Field(default=None, index=False, description="Files in Stored object name")
    user_metadata: dict[str, Any] | None = Field(
        default_factory=dict, sa_column=Column(JsonType, nullable=True), description="User-defined metadata"
    )
    remark: str | None = Field(default="", sa_column=Column(String(length=4096)))
    file_encoding: str | None = Field(
        default=None,
        max_length=64,
        sa_column=Column(String(64), nullable=True),
        description='File encoding for shougang deployment, e.g. "GF-STD-SC-20260500000001". '
        "NULL when shougang is disabled or encoding generation has not run yet.",
    )
    file_subcategory_code: str | None = Field(
        default=None,
        max_length=16,
        sa_column=Column(String(16), nullable=True, index=True),
        description="Second-level file category code for portal filtering. Does not participate in file_encoding.",
    )
    file_subcategory_source: str | None = Field(
        default=None,
        max_length=16,
        sa_column=Column(String(16), nullable=True),
        description="How file_subcategory_code was assigned: manual, ai, or fallback.",
    )
    simhash: str | None = Field(
        default=None,
        max_length=16,
        sa_column=Column(String(16), nullable=True),
        description="64-bit SimHash hex (16 chars). Computed after parse. NULL when not yet computed.",
    )
    similar_status: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
        description="0=no similar / 1=pending (similar detected) / 2=resolved (associated or dismissed).",
    )
    updater_id: int | None = Field(default=None, index=True, description="Last updated by userID")
    updater_name: str | None = Field(default=None, index=True)
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    original_uploader_id: int | None = Field(
        default=None,
        description="User ID that first uploaded the canonical business document",
    )
    original_knowledge_id: int | None = Field(
        default=None,
        description="Knowledge space ID where the canonical business document was first uploaded",
    )
    reference_document_id: int | None = Field(
        default=None,
        description="Canonical KnowledgeDocument referenced by this F059 entry",
    )
    entry_type: str | None = Field(
        default=None,
        sa_column=Column(String(24), nullable=True),
        description="F059 distribution role",
    )
    entry_status: str | None = Field(
        default=None,
        sa_column=Column(String(16), nullable=True),
        description="F059 entry lifecycle state",
    )
    predecessor_logic_file_id: int | None = Field(
        default=None,
        description="Direct publish predecessor KnowledgeFile ID",
    )
    share_source_file_id: int | None = Field(
        default=None,
        description="Manager or publish entry that originated this share",
    )
    allow_download: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
        description="Whether a share entry permits watermarked PDF download",
    )
    approval_instance_id: int | None = Field(
        default=None,
        description="Approval instance that created this entry",
    )
    projection_previous_file_id: int | None = Field(
        default=None,
        description="Previous entry file ID whose projection must be removed",
    )
    desired_content_generation: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    applied_content_generation: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    desired_entry_generation: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    applied_entry_generation: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    projection_status: str = Field(
        default=KnowledgeFileProjectionStatus.PENDING.value,
        sa_column=Column(
            String(16),
            nullable=False,
            server_default=text("'pending'"),
        ),
    )
    projection_retry_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    projection_next_retry_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    projection_lease_owner: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    projection_lease_until: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    projection_last_error: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True, index=True),
        description="Soft-delete timestamp; NULL=active, set when in recycle bin",
    )


class QAKnowledgeBase(SQLModelSerializable):
    user_id: int | None = Field(default=None, index=True)
    knowledge_id: int = Field(index=True)
    questions: list[str] = Field(index=False)
    answers: str = Field(index=False)
    source: int | None = Field(
        default=0, index=False, description="0: Unknown 1: Manual2: Audit, 3: api, 4: Batch import"
    )
    status: int | None = Field(
        default=1,
        index=False,
        description="1: Activate0: Close, the user manually closes;2: Sedang diproses3Failed to insert",
    )
    extra_meta: str | None = Field(default=None, index=False)
    remark: str | None = Field(default="", sa_column=Column(String(length=4096)))
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )

    @field_validator("questions")
    @classmethod
    def validate_json(cls, v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            return v
        if not isinstance(v, list):
            raise ValueError("question must be a valid JSON")

        return v

    @field_validator("answers")
    @classmethod
    def validate_answer(cls, v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            return v
        if isinstance(v, list):
            return json.dumps(v, ensure_ascii=False)

        return v


class KnowledgeFile(KnowledgeFileBase, table=True):
    __table_args__ = (
        Index(
            "idx_kfile_document_space_status",
            "tenant_id",
            "reference_document_id",
            "knowledge_id",
            "entry_status",
        ),
        Index(
            "idx_kfile_document_type_status",
            "tenant_id",
            "reference_document_id",
            "entry_type",
            "entry_status",
        ),
        Index(
            "idx_kfile_projection_retry_lease",
            "tenant_id",
            "projection_status",
            "projection_next_retry_at",
            "projection_lease_until",
        ),
        Index(
            "idx_kfile_entry_cleanup",
            "tenant_id",
            "entry_status",
            "projection_previous_file_id",
        ),
        Index("idx_kfile_predecessor", "predecessor_logic_file_id"),
        Index("idx_kfile_share_source", "share_source_file_id"),
    )
    id: int | None = Field(default=None, primary_key=True)


class QAKnowledge(QAKnowledgeBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    questions: list[str] | None = Field(default=None, sa_column=Column(JsonType))
    answers: str | None = Field(default=None, sa_column=Column(Text))


class KnowledgeFileRead(KnowledgeFileBase):
    id: int


class KnowledgeFileCreate(KnowledgeFileBase):
    pass


class QAKnowledgeUpsert(QAKnowledgeBase):
    """Support modification"""

    id: int | None = None
    answers: list[str] | str | None = None


class KnowledgeFileDao(KnowledgeFileBase):
    _DUPLICATE_EXCLUDED_STATUSES: ClassVar[tuple[int, ...]] = (
        KnowledgeFileStatus.FAILED.value,
        KnowledgeFileStatus.TIMEOUT.value,
        KnowledgeFileStatus.VIOLATION.value,
    )

    @staticmethod
    def active_inventory_predicate():
        """Files that represent one visible inventory item in their local space."""
        from bisheng.knowledge.domain.models.knowledge_document_version import (
            KnowledgeDocumentVersion,
        )

        active_entry = or_(
            KnowledgeFile.reference_document_id.is_(None),
            and_(
                KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
                col(KnowledgeFile.entry_type).in_(
                    [
                        KnowledgeFileEntryType.MANAGER.value,
                        KnowledgeFileEntryType.PUBLISH.value,
                        KnowledgeFileEntryType.SHARE.value,
                    ]
                ),
            ),
        )
        is_historical_version = exists(
            select(KnowledgeDocumentVersion.id).where(
                KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id,
                KnowledgeDocumentVersion.is_primary.is_(False),
            )
        )
        # Soft-deleted recycle-bin rows must not count as inventory.
        return and_(
            active_entry,
            ~is_historical_version,
            col(KnowledgeFile.deleted_at).is_(None),
        )

    @staticmethod
    def physical_storage_predicate():
        """Rows owning physical content, including non-primary versions."""
        return or_(
            KnowledgeFile.entry_type.is_(None),
            KnowledgeFile.entry_type == KnowledgeFileEntryType.MANAGER.value,
        )

    @classmethod
    def _apply_duplicate_filters(cls, statement):
        # Recycled soft-deletes must not block re-upload of the same name/md5.
        return statement.where(
            ~KnowledgeFile.status.in_(cls._DUPLICATE_EXCLUDED_STATUSES),
            col(KnowledgeFile.deleted_at).is_(None),
        )

    @classmethod
    async def query_by_id(cls, file_id: int) -> KnowledgeFile | None:
        async with get_async_db_session() as session:
            result = await session.execute(select(KnowledgeFile).where(KnowledgeFile.id == file_id))
            return result.scalars().first()

    @classmethod
    def query_by_id_sync(cls, file_id: int) -> KnowledgeFile | None:
        with get_sync_db_session() as session:
            return session.exec(select(KnowledgeFile).where(KnowledgeFile.id == file_id)).first()

    @classmethod
    def get_file_simple_by_knowledge_id(cls, knowledge_id: int, page: int, page_size: int):
        offset = (page - 1) * page_size
        with get_sync_db_session() as session:
            return (
                session.query(
                    KnowledgeFile.id,
                    KnowledgeFile.object_name,
                    KnowledgeFile.preview_file_object_name,
                    KnowledgeFile.bbox_object_name,
                    KnowledgeFile.thumbnails,
                    KnowledgeFile.user_metadata,
                    KnowledgeFile.file_name,
                )
                .filter(KnowledgeFile.knowledge_id == knowledge_id)
                .order_by(KnowledgeFile.id.asc())
                .offset(offset)
                .limit(page_size)
                .all()
            )

    @classmethod
    def count_file_by_knowledge_id(cls, knowledge_id: int):
        with get_sync_db_session() as session:
            return (
                session.query(func.count(KnowledgeFile.id)).filter(KnowledgeFile.knowledge_id == knowledge_id).scalar()
            )

    @classmethod
    async def async_count_file_by_knowledge_id(cls, knowledge_id: int):
        statement = select(func.count()).where(KnowledgeFile.knowledge_id == knowledge_id)
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    async def async_count_success_files_batch(cls, knowledge_ids: list[int]) -> dict:
        """Async: Batch count SUCCESS files for multiple knowledge spaces.

        Returns a dict mapping knowledge_id (int) -> success file count.
        """
        if not knowledge_ids:
            return {}
        statement = (
            select(KnowledgeFile.knowledge_id, func.count().label("cnt"))
            .where(
                KnowledgeFile.knowledge_id.in_(knowledge_ids),
                KnowledgeFile.file_type == 1,
                KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
                cls.active_inventory_predicate(),
            )
            .group_by(KnowledgeFile.knowledge_id)
        )
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()
        return {row[0]: row[1] for row in rows}

    @classmethod
    async def async_count_all_success_files(cls) -> int:
        """Count canonical SUCCESS documents across all spaces."""
        statement = select(
            func.count(
                func.distinct(
                    case(
                        (
                            KnowledgeFile.reference_document_id.is_not(None),
                            KnowledgeFile.reference_document_id,
                        ),
                        else_=KnowledgeFile.id,
                    )
                )
            )
        ).where(
            KnowledgeFile.file_type == 1,
            KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
            cls.active_inventory_predicate(),
        )
        async with get_async_db_session() as session:
            result = (await session.exec(statement)).one()
        return int(result or 0)

    @classmethod
    async def async_count_files_by_domain_codes(cls, codes: list[str]) -> dict:
        """Async: count SUCCESS document files per business-domain code across ALL knowledge bases.

        Business code = second-from-last segment (robust to multi-segment prefixes).
        file_encoding is '{prefix}-{type}-{business}-{ym}{seq}'; the operator-configured
        prefix may contain dashes, but the trailing serial '{ym}{seq}' is always a single
        dash-free segment, so the business code is always the second-from-last '-'-segment
        (e.g. 'GF-STD-SC-2026...' -> 'SC'). Counts only file_type==FILE and
        status==SUCCESS files. Returns {code: count} for every requested code
        (codes with no match -> 0). Login/space filters are intentionally ignored.
        """
        normalized = sorted({c.strip().upper() for c in codes if c and c.strip()})
        if not normalized:
            return {}
        like_conditions = [col(KnowledgeFile.file_encoding).like(f"%-{code}-%") for code in normalized]
        statement = select(
            KnowledgeFile.id,
            KnowledgeFile.reference_document_id,
            KnowledgeFile.file_encoding,
        ).where(
            KnowledgeFile.file_type == FileType.FILE.value,
            KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
            col(KnowledgeFile.file_encoding).is_not(None),
            or_(*like_conditions),
            cls.active_inventory_predicate(),
        )
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()
        canonical_ids_by_code = {code: set() for code in normalized}
        code_set = set(normalized)
        for file_id, document_id, encoding in rows:
            parts = (encoding or "").split("-")
            if len(parts) >= 3:
                # business code = second-from-last segment (robust to multi-segment prefixes)
                domain = parts[-2].strip().upper()
                if domain in code_set:
                    canonical_ids_by_code[domain].add(int(document_id or file_id))
        return {code: len(canonical_ids) for code, canonical_ids in canonical_ids_by_code.items()}

    @classmethod
    async def async_count_files_by_domain_scopes(
        cls,
        domain_space_ids: dict[str, set[int]],
        domain_file_ids: dict[str, set[int]] | None = None,
    ) -> dict[str, int]:
        """Count successful files for each business-domain and knowledge-space scope."""
        normalized_scopes = {
            code.strip().upper(): {int(space_id) for space_id in space_ids if int(space_id) > 0}
            for code, space_ids in domain_space_ids.items()
            if code and code.strip()
        }
        normalized_file_scopes = {
            code.strip().upper(): {int(file_id) for file_id in file_ids if int(file_id) > 0}
            for code, file_ids in (domain_file_ids or {}).items()
            if code and code.strip()
        }
        codes = set(normalized_scopes) | set(normalized_file_scopes)
        counts = dict.fromkeys(codes, 0)
        conditions = []
        for code in codes:
            resource_conditions = []
            if space_ids := normalized_scopes.get(code):
                resource_conditions.append(KnowledgeFile.knowledge_id.in_(space_ids))
            if file_ids := normalized_file_scopes.get(code):
                resource_conditions.append(KnowledgeFile.id.in_(file_ids))
            if resource_conditions:
                conditions.append(
                    and_(
                        or_(*resource_conditions),
                        col(KnowledgeFile.file_encoding).like(f"%-{code}-%"),
                    )
                )
        if not conditions:
            return counts
        statement = select(
            KnowledgeFile.id,
            KnowledgeFile.reference_document_id,
            KnowledgeFile.knowledge_id,
            KnowledgeFile.file_encoding,
        ).where(
            KnowledgeFile.file_type == FileType.FILE.value,
            KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
            col(KnowledgeFile.file_encoding).is_not(None),
            or_(*conditions),
            cls.active_inventory_predicate(),
        )
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()
        canonical_ids_by_code = {code: set() for code in codes}
        for file_id, document_id, knowledge_id, encoding in rows:
            parts = (encoding or "").split("-")
            if len(parts) < 3:
                continue
            code = parts[-2].strip().upper()
            if (
                knowledge_id in normalized_scopes.get(code, set())
                or file_id in normalized_file_scopes.get(code, set())
            ):
                canonical_ids_by_code[code].add(int(document_id or file_id))
        return {code: len(canonical_ids_by_code[code]) for code in counts}

    @classmethod
    async def async_count_files_by_category_scopes(
        cls,
        category_space_ids: dict[str, set[int]],
        category_file_ids: dict[str, set[int]] | None = None,
    ) -> dict[str, int]:
        """Count active canonical documents per category within each card scope."""
        normalized_scopes = {
            code.strip().upper(): {int(space_id) for space_id in space_ids if int(space_id) > 0}
            for code, space_ids in category_space_ids.items()
            if code and code.strip()
        }
        normalized_file_scopes = {
            code.strip().upper(): {int(file_id) for file_id in file_ids if int(file_id) > 0}
            for code, file_ids in (category_file_ids or {}).items()
            if code and code.strip()
        }
        codes = set(normalized_scopes) | set(normalized_file_scopes)
        counts = dict.fromkeys(codes, 0)
        conditions = []
        for code in codes:
            resource_conditions = []
            if space_ids := normalized_scopes.get(code):
                resource_conditions.append(KnowledgeFile.knowledge_id.in_(space_ids))
            if file_ids := normalized_file_scopes.get(code):
                resource_conditions.append(KnowledgeFile.id.in_(file_ids))
            if resource_conditions:
                conditions.append(
                    and_(
                        or_(*resource_conditions),
                        col(KnowledgeFile.file_encoding).like(f"%-{code}-%"),
                    )
                )
        if not conditions:
            return counts
        statement = select(
            KnowledgeFile.id,
            KnowledgeFile.reference_document_id,
            KnowledgeFile.knowledge_id,
            KnowledgeFile.file_encoding,
        ).where(
            KnowledgeFile.file_type == FileType.FILE.value,
            KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
            col(KnowledgeFile.file_encoding).is_not(None),
            or_(*conditions),
            cls.active_inventory_predicate(),
        )
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()
        canonical_ids_by_code = {code: set() for code in codes}
        for file_id, document_id, knowledge_id, encoding in rows:
            document_code, _ = parse_shougang_file_encoding_codes({"file_encoding": encoding})
            document_code = (document_code or "").strip().upper()
            if not document_code:
                continue
            if (
                int(knowledge_id) in normalized_scopes.get(document_code, set())
                or int(file_id) in normalized_file_scopes.get(document_code, set())
            ):
                canonical_ids_by_code[document_code].add(int(document_id or file_id))
        return {code: len(canonical_ids_by_code[code]) for code in counts}

    @classmethod
    def delete_batch(cls, file_ids: list[int]) -> bool:
        with get_sync_db_session() as session:
            session.exec(delete(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids)))
            session.commit()
            return True

    @classmethod
    async def adelete_batch(cls, file_ids: list[int]) -> bool:
        async with get_async_db_session() as session:
            await session.exec(delete(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids)))
            await session.commit()
            return True

    @classmethod
    def add_file(cls, knowledge_file: KnowledgeFile) -> KnowledgeFile:
        with get_sync_db_session() as session:
            session.add(knowledge_file)
            session.commit()
            session.refresh(knowledge_file)
        return knowledge_file

    @classmethod
    def get_user_upload_total_file_size(cls, user_id: int) -> int:
        """Total bytes for active files uploaded by a user."""
        statement = select(func.sum(KnowledgeFile.file_size)).where(
            KnowledgeFile.user_id == user_id,
            KnowledgeFile.file_type == FileType.FILE.value,
            cls.physical_storage_predicate(),
            col(KnowledgeFile.deleted_at).is_(None),
            KnowledgeFile.status.in_(
                [
                    KnowledgeFileStatus.PROCESSING.value,
                    KnowledgeFileStatus.SUCCESS.value,
                    KnowledgeFileStatus.WAITING.value,
                ]
            ),
        )
        with get_sync_db_session() as session:
            return session.scalar(statement) or 0

    @classmethod
    async def aget_user_upload_total_file_size(cls, user_id: int) -> int:
        """Async total bytes for active files uploaded by a user."""
        statement = select(func.sum(KnowledgeFile.file_size)).where(
            KnowledgeFile.user_id == user_id,
            KnowledgeFile.file_type == FileType.FILE.value,
            cls.physical_storage_predicate(),
            col(KnowledgeFile.deleted_at).is_(None),
            KnowledgeFile.status.in_(
                [
                    KnowledgeFileStatus.PROCESSING.value,
                    KnowledgeFileStatus.SUCCESS.value,
                    KnowledgeFileStatus.WAITING.value,
                ]
            ),
        )
        async with get_async_db_session() as session:
            return await session.scalar(statement) or 0

    @classmethod
    async def aadd_file(cls, knowledge_file: KnowledgeFile) -> KnowledgeFile:
        async with get_async_db_session() as session:
            session.add(knowledge_file)
            await session.commit()
            await session.refresh(knowledge_file)
            return knowledge_file

    @classmethod
    def update(cls, knowledge_file):
        with get_sync_db_session() as session:
            session.add(knowledge_file)
            session.commit()
            session.refresh(knowledge_file)
        return knowledge_file

    @classmethod
    async def async_update(cls, knowledge_file):
        async with get_async_db_session() as session:
            session.add(knowledge_file)
            await session.commit()
            await session.refresh(knowledge_file)
        return knowledge_file

    @classmethod
    async def async_update_sort_weights(cls, weight_by_file_id: dict[int, int]) -> None:
        """Write manual sort weights for the given folders.

        Used both for a single drag (one row) and for (re)assigning a whole directory's
        weights, so it stays one round-trip per row rather than loading ORM objects.
        Callers own the ordering semantics.
        """
        if not weight_by_file_id:
            return
        async with get_async_db_session() as session:
            for file_id, weight in weight_by_file_id.items():
                await session.exec(
                    update(KnowledgeFile).where(KnowledgeFile.id == int(file_id)).values(sort_weight=int(weight))
                )
            await session.commit()

    @classmethod
    async def async_update_batch(cls, knowledge_files: list[KnowledgeFile]) -> bool:
        if not knowledge_files:
            return False
        async with get_async_db_session() as session:
            session.add_all(knowledge_files)
            await session.commit()
            return True

    @classmethod
    def update_file_status(cls, file_ids: list[int], status: KnowledgeFileStatus, reason: str = None):
        """Batch update file status"""
        statement = (
            update(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids)).values(status=status.value, remark=reason)
        )
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    async def aupdate_file_status(cls, file_ids: list[int], status: KnowledgeFileStatus, reason: str = None):
        """Batch update file status"""
        statement = (
            update(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids)).values(status=status.value, remark=reason)
        )
        async with get_async_db_session() as session:
            await session.exec(statement)
            await session.commit()

    @classmethod
    def get_file_by_condition(cls, knowledge_id: int, md5_: str = None, file_name: str = None):
        with get_sync_db_session() as session:
            sql = cls._apply_duplicate_filters(select(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id))
            if md5_:
                sql = sql.where(KnowledgeFile.md5 == md5_)
            if file_name:
                sql = sql.where(KnowledgeFile.file_name == file_name)
            return session.exec(sql).all()

    @classmethod
    async def get_repeat_file(cls, knowledge_id: int, md5_: str = None, file_name: str = None):
        # Mirror the list-rendering rule: hide files that are no longer the
        # primary version of any chain. Legacy files (no version row at all)
        # still count as visible. Otherwise an orphaned non-primary leftover
        # from a botched set_primary / link flow would invisibly block uploads
        # of the same md5 because the UI says "nothing here" but the dup
        # checker can still see it.
        from sqlalchemy import exists

        from bisheng.knowledge.domain.models.knowledge_document_version import (
            KnowledgeDocumentVersion,
        )

        primary_version = (
            select(KnowledgeDocumentVersion.id)
            .where(KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id)
            .where(KnowledgeDocumentVersion.is_primary == True)  # noqa: E712
        )
        any_version = select(KnowledgeDocumentVersion.id).where(
            KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id
        )

        sql = cls._apply_duplicate_filters(select(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id))
        sql = sql.where(
            or_(
                ~exists(any_version),  # legacy file outside the version system
                exists(primary_version),  # current primary of its chain
            )
        )

        if md5_ and file_name:
            sql = sql.where(or_(KnowledgeFile.md5 == md5_, KnowledgeFile.file_name == file_name))
        elif md5_:
            sql = sql.where(KnowledgeFile.md5 == md5_)
        elif file_name:
            sql = sql.where(KnowledgeFile.file_name == file_name)
        async with get_async_db_session() as session:
            result = await session.exec(sql)
            return result.first()

    @classmethod
    def select_list(cls, file_ids: list[int]):
        if not file_ids:
            return []
        with get_sync_db_session() as session:
            knowledge_files = session.exec(select(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids))).all()
        if not knowledge_files:
            raise ValueError("Doc.IDDoes not exist")
        return knowledge_files

    @classmethod
    def get_file_by_ids(cls, file_ids: list[int]) -> list[KnowledgeFile]:
        if not file_ids:
            return []
        with get_sync_db_session() as session:
            return session.exec(select(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids))).all()

    @classmethod
    async def aget_file_by_ids(cls, file_ids: list[int]) -> list[KnowledgeFile]:
        if not file_ids:
            return []
        stat = select(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids))
        async with get_async_db_session() as session:
            return (await session.exec(stat)).all()

    @classmethod
    async def aget_folders_by_space(cls, knowledge_id: int) -> list[KnowledgeFile]:
        statement = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.knowledge_id == knowledge_id,
                KnowledgeFile.file_type == FileType.DIR.value,
                col(KnowledgeFile.deleted_at).is_(None),
            )
            .order_by(col(KnowledgeFile.level).asc(), col(KnowledgeFile.id).asc())
        )
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    def _build_file_filters_statement(
        cls,
        statement,
        file_name: str = None,
        status: list[int] = None,
        file_ids: list[int] = None,
        file_level_path: str = None,
        extra_file_ids: list[int] = None,
        file_type: int = None,
        *,
        order_by: str = None,
        order_field: str = None,
        order_sort: str = "desc",
        match_file_encoding: bool = False,
    ):
        and_statement = []
        if status:
            and_statement.append(KnowledgeFile.status.in_(status))
        if file_ids:
            and_statement.append(KnowledgeFile.id.in_(file_ids))
        if file_level_path:
            and_statement.append(KnowledgeFile.file_level_path.like(f"{file_level_path}%"))
        if file_type is not None:
            and_statement.append(KnowledgeFile.file_type == file_type)

        name_match = None
        if file_name:
            name_match = KnowledgeFile.file_name.like(f"%{file_name}%")
            if match_file_encoding:
                name_match = or_(
                    name_match,
                    KnowledgeFile.file_encoding.like(f"%{file_name}%"),
                )

        keyword_statement = None
        if name_match is not None and extra_file_ids:
            keyword_statement = or_(
                name_match,
                KnowledgeFile.id.in_(extra_file_ids),
            )
        elif name_match is not None:
            keyword_statement = name_match
        elif extra_file_ids:
            keyword_statement = KnowledgeFile.id.in_(extra_file_ids)

        if keyword_statement is not None:
            and_statement.append(keyword_statement)

        statement = statement.where(*and_statement)

        if order_field and order_sort:
            from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao

            statement = statement.order_by(text(SpaceFileDao.order_field_text(order_field, order_sort)))
        elif order_by == "file_type":
            statement = statement.order_by(col(KnowledgeFile.file_type).asc())
        elif order_by == "update_time":
            statement = statement.order_by(col(KnowledgeFile.update_time).desc())
        return statement

    @classmethod
    def get_file_by_filters(
        cls,
        knowledge_id: int,
        file_name: str = None,
        status: list[int] = None,
        page: int = 0,
        page_size: int = 0,
        file_ids: list[int] = None,
    ) -> list[KnowledgeFile]:
        statement = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            col(KnowledgeFile.deleted_at).is_(None),
        )
        statement = cls._build_file_filters_statement(statement, file_name, status, file_ids, order_by="update_time")
        if page and page_size:
            statement = statement.offset((page - 1) * page_size).limit(page_size)
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_file_by_filters(
        cls,
        knowledge_id: int,
        file_name: str = None,
        status: list[int] = None,
        file_ids: list[int] = None,
        extra_file_ids: list[int] = None,
        file_level_path: str = None,
        order_by: str = None,
        order_field: str = None,
        order_sort: str = "desc",
        file_type: int = None,
        *,
        page: int = 0,
        page_size: int = 0,
        exclude_file_ids: list[int] | None = None,
    ) -> list[KnowledgeFile]:
        statement = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            col(KnowledgeFile.deleted_at).is_(None),
        )
        statement = cls._build_file_filters_statement(
            statement,
            file_name,
            status,
            file_ids,
            file_level_path,
            extra_file_ids=extra_file_ids,
            file_type=file_type,
            order_by=order_by,
            order_field=order_field,
            order_sort=order_sort,
        )
        if exclude_file_ids:
            statement = statement.where(col(KnowledgeFile.id).notin_(exclude_file_ids))
        if page and page_size:
            statement = statement.offset((page - 1) * page_size).limit(page_size)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    async def aget_file_by_space_filters(
        cls,
        knowledge_ids: list[int],
        file_name: str = None,
        status: list[int] = None,
        file_ids: list[int] = None,
        extra_file_ids: list[int] = None,
        file_ext: str = None,
        file_subcategory_code: str = None,
        order_by: str = None,
        order_field: str = None,
        order_sort: str = "desc",
        match_file_encoding: bool = False,
    ) -> list[KnowledgeFile]:
        unique_knowledge_ids = list(dict.fromkeys(int(knowledge_id) for knowledge_id in knowledge_ids if knowledge_id))
        if not unique_knowledge_ids:
            return []
        statement = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id.in_(unique_knowledge_ids),
            KnowledgeFile.file_type == FileType.FILE.value,
            col(KnowledgeFile.deleted_at).is_(None),
        )
        statement = cls._build_file_filters_statement(
            statement,
            file_name,
            status,
            file_ids,
            extra_file_ids=extra_file_ids,
            order_by=order_by,
            order_field=order_field,
            order_sort=order_sort,
            match_file_encoding=match_file_encoding,
        )
        normalized_ext = (file_ext or "").strip().lower().lstrip(".")
        if normalized_ext:
            statement = statement.where(func.lower(KnowledgeFile.file_name).like(f"%.{normalized_ext}"))
        normalized_file_subcategory_code = (file_subcategory_code or "").strip().upper()
        if normalized_file_subcategory_code:
            statement = statement.where(KnowledgeFile.file_subcategory_code == normalized_file_subcategory_code)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    async def aget_file_by_space_filters_cursor(
        cls,
        knowledge_ids: list[int],
        file_name: str = None,
        status: list[int] = None,
        file_ids: list[int] = None,
        extra_file_ids: list[int] = None,
        file_ext: str = None,
        document_type: str = None,
        file_subcategory_code: str = None,
        business_domain_code: str = None,
        full_space_ids: list[int] | None = None,
        explicit_file_ids: list[int] | None = None,
        order_sort: str = "desc",
        cursor: list[Any] | None = None,
        limit: int = 20,
        match_file_encoding: bool = False,
    ) -> list[KnowledgeFile]:
        unique_knowledge_ids = list(dict.fromkeys(int(knowledge_id) for knowledge_id in knowledge_ids if knowledge_id))
        if not unique_knowledge_ids:
            return []

        canonical_document_id = func.coalesce(
            KnowledgeFile.reference_document_id,
            KnowledgeFile.id,
        )
        space_priority = case(
            *(
                (KnowledgeFile.knowledge_id == knowledge_id, index)
                for index, knowledge_id in enumerate(unique_knowledge_ids)
            ),
            else_=len(unique_knowledge_ids),
        )
        entry_priority = case(
            (KnowledgeFile.entry_type.is_(None), 0),
            (KnowledgeFile.entry_type == KnowledgeFileEntryType.MANAGER.value, 0),
            (KnowledgeFile.entry_type == KnowledgeFileEntryType.PUBLISH.value, 1),
            (KnowledgeFile.entry_type == KnowledgeFileEntryType.SHARE.value, 2),
            else_=9,
        )
        canonical_rank = func.row_number().over(
            partition_by=canonical_document_id,
            order_by=(space_priority.asc(), entry_priority.asc(), KnowledgeFile.id.asc()),
        ).label("canonical_rank")
        ranked_statement = select(
            KnowledgeFile.id.label("file_id"),
            canonical_rank,
        ).where(
            KnowledgeFile.knowledge_id.in_(unique_knowledge_ids),
            KnowledgeFile.file_type == FileType.FILE.value,
            cls.active_inventory_predicate(),
        )
        if full_space_ids is not None or explicit_file_ids is not None:
            normalized_full_space_ids = {
                int(space_id) for space_id in (full_space_ids or []) if int(space_id) > 0
            }
            normalized_explicit_file_ids = {
                int(file_id) for file_id in (explicit_file_ids or []) if int(file_id) > 0
            }
            visibility_conditions = []
            if normalized_full_space_ids:
                visibility_conditions.append(KnowledgeFile.knowledge_id.in_(normalized_full_space_ids))
            if normalized_explicit_file_ids:
                visibility_conditions.append(KnowledgeFile.id.in_(normalized_explicit_file_ids))
            if not visibility_conditions:
                return []
            ranked_statement = ranked_statement.where(or_(*visibility_conditions))
        ranked_statement = cls._build_file_filters_statement(
            ranked_statement,
            file_name,
            status,
            file_ids,
            extra_file_ids=extra_file_ids,
            match_file_encoding=match_file_encoding,
        )

        normalized_ext = (file_ext or "").strip().lower().lstrip(".")
        if normalized_ext:
            ranked_statement = ranked_statement.where(
                func.lower(KnowledgeFile.file_name).like(f"%.{normalized_ext}")
            )

        normalized_file_subcategory_code = (file_subcategory_code or "").strip().upper()
        if normalized_file_subcategory_code:
            ranked_statement = ranked_statement.where(
                KnowledgeFile.file_subcategory_code == normalized_file_subcategory_code
            )

        normalized_document_type = (document_type or "").strip().upper()
        if normalized_document_type:
            ranked_statement = ranked_statement.where(
                KnowledgeFile.file_encoding.like(f"%-{normalized_document_type}-%")
            )

        normalized_business_domain_code = (business_domain_code or "").strip().upper()
        if normalized_business_domain_code:
            ranked_statement = ranked_statement.where(
                KnowledgeFile.file_encoding.like(f"%-{normalized_business_domain_code}-%")
            )

        ranked_files = ranked_statement.subquery()
        statement = select(KnowledgeFile).join(
            ranked_files,
            KnowledgeFile.id == ranked_files.c.file_id,
        ).where(ranked_files.c.canonical_rank == 1)

        normalized_order_sort = "asc" if str(order_sort or "").lower() == "asc" else "desc"
        if cursor and len(cursor) >= 2:
            cursor_update_time = cursor[0]
            cursor_id = int(cursor[1])
            if normalized_order_sort == "asc":
                statement = statement.where(
                    or_(
                        col(KnowledgeFile.update_time) > cursor_update_time,
                        and_(
                            col(KnowledgeFile.update_time) == cursor_update_time,
                            col(KnowledgeFile.id) > cursor_id,
                        ),
                    )
                )
            else:
                statement = statement.where(
                    or_(
                        col(KnowledgeFile.update_time) < cursor_update_time,
                        and_(
                            col(KnowledgeFile.update_time) == cursor_update_time,
                            col(KnowledgeFile.id) < cursor_id,
                        ),
                    )
                )

        if normalized_order_sort == "asc":
            statement = statement.order_by(col(KnowledgeFile.update_time).asc(), col(KnowledgeFile.id).asc())
        else:
            statement = statement.order_by(col(KnowledgeFile.update_time).desc(), col(KnowledgeFile.id).desc())

        safe_limit = min(max(int(limit or 20), 1), 500)
        statement = statement.limit(safe_limit)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    async def asearch_portal_advanced_cursor(
        cls,
        *,
        knowledge_ids: list[int],
        status: list[int] | None = None,
        tag_ids: list[int] | None = None,
        file_ext: str | None = None,
        document_type: str | None = None,
        file_subcategory_code: str | None = None,
        business_domain_code: str | None = None,
        all_keywords: str | None = None,
        exact_phrase: str | None = None,
        any_keywords: str | None = None,
        exclude_keywords: str | None = None,
        search_field: Literal["file_name", "summary", "tags"] = "file_name",
        updated_from: date | None = None,
        updated_to: date | None = None,
        order_sort: str = "desc",
        cursor: list[Any] | None = None,
        limit: int = 20,
    ) -> list[KnowledgeFile]:
        from bisheng.database.models.group_resource import ResourceTypeEnum
        from bisheng.database.models.tag import Tag, TagLink
        from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
        from bisheng.knowledge.domain.models.knowledge_document_version import (
            KnowledgeDocumentVersion,
        )

        unique_knowledge_ids = list(
            dict.fromkeys(int(knowledge_id) for knowledge_id in knowledge_ids if int(knowledge_id) > 0)
        )
        if not unique_knowledge_ids:
            return []

        statement = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id.in_(unique_knowledge_ids),
            KnowledgeFile.file_type == FileType.FILE.value,
            col(KnowledgeFile.deleted_at).is_(None),
        )
        statement = cls._build_file_filters_statement(
            statement,
            status=status,
        )

        normalized_ext = (file_ext or "").strip().lower().lstrip(".")
        if normalized_ext:
            statement = statement.where(func.lower(KnowledgeFile.file_name).like(f"%.{normalized_ext}"))
        normalized_document_type = (document_type or "").strip().upper()
        if normalized_document_type:
            statement = statement.where(KnowledgeFile.file_encoding.like(f"%-{normalized_document_type}-%"))
        normalized_subcategory = (file_subcategory_code or "").strip().upper()
        if normalized_subcategory:
            statement = statement.where(KnowledgeFile.file_subcategory_code == normalized_subcategory)
        normalized_domain = (business_domain_code or "").strip().upper()
        if normalized_domain:
            statement = statement.where(KnowledgeFile.file_encoding.like(f"%-{normalized_domain}-%"))

        primary_file_id = (
            select(KnowledgeDocumentVersion.knowledge_file_id)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.primary_version_id == KnowledgeDocumentVersion.id,
            )
            .where(KnowledgeDocument.id == KnowledgeFile.reference_document_id)
            .correlate(KnowledgeFile)
            .scalar_subquery()
        )
        tag_source_file_id = func.coalesce(primary_file_id, KnowledgeFile.id)

        def tag_exists(
            *,
            keyword: str | None = None,
            required_tag_ids: list[int] | None = None,
        ):
            tag_statement = (
                select(TagLink.id)
                .join(Tag, Tag.id == TagLink.tag_id)
                .where(
                    TagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                    TagLink.resource_id == cast(tag_source_file_id, String),
                )
                .correlate(KnowledgeFile)
            )
            if required_tag_ids:
                tag_statement = tag_statement.where(TagLink.tag_id.in_(required_tag_ids))
            if keyword:
                tag_statement = tag_statement.where(
                    func.lower(func.coalesce(Tag.name, "")).contains(
                        keyword,
                        autoescape=True,
                    )
                )
            return exists(tag_statement)

        if tag_ids:
            statement = statement.where(tag_exists(required_tag_ids=tag_ids))

        if search_field == "summary":
            searchable_text = func.lower(func.coalesce(KnowledgeFile.abstract, ""))
        else:
            searchable_text = func.lower(func.coalesce(KnowledgeFile.file_name, ""))

        def matches_keyword(keyword: str):
            if search_field == "tags":
                return tag_exists(keyword=keyword)
            return searchable_text.contains(keyword, autoescape=True)

        all_terms = [term.casefold() for term in (all_keywords or "").split() if term.strip()]
        any_terms = [term.casefold() for term in (any_keywords or "").split() if term.strip()]
        excluded_terms = [term.casefold() for term in (exclude_keywords or "").split() if term.strip()]
        normalized_phrase = (exact_phrase or "").strip().casefold()
        for term in all_terms:
            statement = statement.where(matches_keyword(term))
        if normalized_phrase:
            statement = statement.where(matches_keyword(normalized_phrase))
        if any_terms:
            statement = statement.where(or_(*(matches_keyword(term) for term in any_terms)))
        if excluded_terms:
            statement = statement.where(~or_(*(matches_keyword(term) for term in excluded_terms)))

        if updated_from is not None:
            statement = statement.where(KnowledgeFile.update_time >= datetime.combine(updated_from, time.min))
        if updated_to is not None:
            statement = statement.where(
                KnowledgeFile.update_time < datetime.combine(updated_to + timedelta(days=1), time.min)
            )

        normalized_order_sort = "asc" if str(order_sort or "").lower() == "asc" else "desc"
        if cursor and len(cursor) >= 2:
            cursor_update_time = cursor[0]
            cursor_id = int(cursor[1])
            if normalized_order_sort == "asc":
                statement = statement.where(
                    or_(
                        col(KnowledgeFile.update_time) > cursor_update_time,
                        and_(
                            col(KnowledgeFile.update_time) == cursor_update_time,
                            col(KnowledgeFile.id) > cursor_id,
                        ),
                    )
                )
            else:
                statement = statement.where(
                    or_(
                        col(KnowledgeFile.update_time) < cursor_update_time,
                        and_(
                            col(KnowledgeFile.update_time) == cursor_update_time,
                            col(KnowledgeFile.id) < cursor_id,
                        ),
                    )
                )

        if normalized_order_sort == "asc":
            statement = statement.order_by(
                col(KnowledgeFile.update_time).asc(),
                col(KnowledgeFile.id).asc(),
            )
        else:
            statement = statement.order_by(
                col(KnowledgeFile.update_time).desc(),
                col(KnowledgeFile.id).desc(),
            )

        safe_limit = min(max(int(limit or 20), 1), 500)
        statement = statement.limit(safe_limit)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    async def alist_user_uploaded_files(
        cls,
        *,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        space_id: int | None = None,
        status: int | None = None,
        keyword: str | None = None,
        file_sources: tuple[str, ...] | None = None,
    ) -> tuple[list[KnowledgeFile], int]:
        safe_page = max(int(page or 1), 1)
        safe_page_size = min(max(int(page_size or 20), 1), 100)
        sources = file_sources or PORTAL_USER_UPLOAD_FILE_SOURCES
        filters = [
            KnowledgeFile.user_id == user_id,
            KnowledgeFile.file_type == FileType.FILE.value,
            col(KnowledgeFile.deleted_at).is_(None),
        ]
        if sources:
            filters.append(KnowledgeFile.file_source.in_(sources))
        if space_id is not None:
            filters.append(KnowledgeFile.knowledge_id == space_id)
        if status is not None:
            filters.append(KnowledgeFile.status == status)
        cleaned_keyword = (keyword or "").strip()
        if cleaned_keyword:
            filters.append(KnowledgeFile.file_name.like(f"%{cleaned_keyword}%"))

        count_statement = select(func.count()).where(*filters)
        statement = (
            select(KnowledgeFile)
            .where(*filters)
            .order_by(col(KnowledgeFile.create_time).desc(), col(KnowledgeFile.id).desc())
            .offset((safe_page - 1) * safe_page_size)
            .limit(safe_page_size)
        )
        async with get_async_db_session() as session:
            total = await session.scalar(count_statement) or 0
            rows = (await session.exec(statement)).all()
        return rows, int(total)

    @classmethod
    async def aget_references_by_knowledge_id(
        cls,
        knowledge_id: int,
        page: int | None = None,
        page_size: int | None = None,
    ) -> tuple[list[KnowledgeFile], int]:
        """查询某收藏库下的引用型收藏记录（file_source=='favorite_reference'），按 id 倒序。

        不传 page 时返回全部记录 + total；传 page/page_size 时返回该页 + total。
        A5 复用此方法，签名稳定。
        """
        filters = [
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.file_source == "favorite_reference",
        ]
        count_statement = select(func.count()).where(*filters)
        statement = select(KnowledgeFile).where(*filters).order_by(col(KnowledgeFile.id).desc())
        if page is not None and page_size is not None:
            safe_page = max(int(page or 1), 1)
            safe_page_size = max(int(page_size or 1), 1)
            statement = statement.offset((safe_page - 1) * safe_page_size).limit(safe_page_size)
        async with get_async_db_session() as session:
            total = await session.scalar(count_statement) or 0
            rows = (await session.exec(statement)).all()
        return rows, int(total)

    @staticmethod
    def _match_favorite_referrer(row, source_file_id: int) -> bool:
        """判断一条引用记录是否收藏了指定源文件。

        引用记录的 user_metadata 形如 {"favorite_reference": {"source_space_id": .., "source_file_id": ..}}。
        source_file_id 以 JSON 存储、可能为 str/int，这里统一转 int 比较。
        """
        meta = (getattr(row, "user_metadata", None) or {}).get("favorite_reference") or {}
        try:
            return int(meta.get("source_file_id") or 0) == int(source_file_id)
        except (TypeError, ValueError):
            return False

    @classmethod
    async def aget_favorite_referrers(cls, source_file_id: int) -> list[KnowledgeFile]:
        """反查：找出所有『收藏了指定源文件』的引用记录（跨用户、跨收藏库）。

        返回 file_source=='favorite_reference' 且
        user_metadata.favorite_reference.source_file_id == source_file_id 的记录。
        每条记录携带 user_id（收藏者）与 knowledge_id（该收藏者自己的收藏库 id），
        供源文件变更时向收藏者发送站内信 + 跳转到其收藏库。

        收藏引用量小，采用「SQL 过滤 file_source + Python 过滤 JSON」的跨方言稳妥实现，
        避免依赖各数据库对 JSON 函数的差异（MySQL / 达梦）。
        """
        try:
            fid = int(source_file_id)
        except (TypeError, ValueError):
            return []
        if fid <= 0:
            return []
        statement = select(KnowledgeFile).where(KnowledgeFile.file_source == "favorite_reference")
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()
        return [row for row in rows if cls._match_favorite_referrer(row, fid)]

    @classmethod
    async def acount_by_file_encoding(cls, file_encoding: str, exclude_id: int | None = None) -> int:
        cleaned = (file_encoding or "").strip()
        if not cleaned:
            return 0
        statement = select(func.count()).where(
            KnowledgeFile.file_type == FileType.FILE.value,
            KnowledgeFile.file_encoding == cleaned,
            col(KnowledgeFile.deleted_at).is_(None),
        )
        if exclude_id is not None:
            statement = statement.where(KnowledgeFile.id != exclude_id)
        async with get_async_db_session() as session:
            return int(await session.scalar(statement) or 0)

    @classmethod
    async def aget_files_by_file_encoding(
        cls,
        file_encoding: str,
        knowledge_id: int | None = None,
    ) -> list[KnowledgeFile]:
        cleaned = (file_encoding or "").strip()
        if not cleaned:
            return []
        statement = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.file_type == FileType.FILE.value,
                KnowledgeFile.file_encoding == cleaned,
                col(KnowledgeFile.deleted_at).is_(None),
            )
            .order_by(col(KnowledgeFile.id).asc())
        )
        if knowledge_id is not None:
            statement = statement.where(KnowledgeFile.knowledge_id == knowledge_id)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    async def acount_file_by_filters(
        cls,
        knowledge_id: int,
        file_name: str = None,
        status: list[int] = None,
        file_ids: list[int] = None,
        extra_file_ids: list[int] = None,
        file_level_path: str = None,
        file_type: int = None,
    ) -> int:
        statement = select(func.count()).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            col(KnowledgeFile.deleted_at).is_(None),
        )
        statement = cls._build_file_filters_statement(
            statement, file_name, status, file_ids, file_level_path, extra_file_ids=extra_file_ids, file_type=file_type
        )
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    def get_files_by_multiple_status(cls, knowledge_id: int, status_list: list[int]) -> list[KnowledgeFile]:
        """
        Based on Knowledge BaseIDand status list query file

        Args:
            knowledge_id: The knowledge base uponID
            status_list: List of status values

        Returns:
            List[KnowledgeFile]: Matching Files List
        """
        statement = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.status.in_(status_list),
            col(KnowledgeFile.deleted_at).is_(None),
        )

        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def count_file_by_filters(
        cls, knowledge_id: int, file_name: str = None, status: list[int] = None, file_ids: list[int] = None
    ) -> int:
        statement = select(func.count(KnowledgeFile.id)).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            col(KnowledgeFile.deleted_at).is_(None),
        )
        if file_name:
            statement = statement.where(KnowledgeFile.file_name.like(f"%{file_name}%"))
        if status:
            statement = statement.where(KnowledgeFile.status.in_(status))
        if file_ids:
            statement = statement.where(KnowledgeFile.id.in_(file_ids))
        with get_sync_db_session() as session:
            return session.scalar(statement)

    @classmethod
    async def async_count_file_by_filters(
        cls, knowledge_id: int, file_name: str = None, status: list[int] = None, file_ids: list[int] = None
    ) -> int:
        statement = select(func.count(KnowledgeFile.id)).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            col(KnowledgeFile.deleted_at).is_(None),
        )
        if file_name:
            statement = statement.where(KnowledgeFile.file_name.like(f"%{file_name}%"))
        if status:
            statement = statement.where(KnowledgeFile.status.in_(status))
        if file_ids:
            statement = statement.where(KnowledgeFile.id.in_(file_ids))
        async with get_async_db_session() as session:
            result = await session.execute(statement)
            return result.scalar_one()

    @classmethod
    def get_knowledge_ids_by_name(cls, file_name: str) -> list[int]:
        statement = (
            select(KnowledgeFile.knowledge_id)
            .where(KnowledgeFile.file_name.like(f"%{file_name}%"))
            .group_by(KnowledgeFile.knowledge_id)
        )
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def update_status_bulk(cls, file_ids: list[int], status: KnowledgeFileStatus, remark: str = "") -> None:
        """
        Batch update file status

        Args:
            file_ids: Doc.IDVertical
            status: New status value

        Returns:
            None
        """
        if not file_ids:
            return

        statement = update(KnowledgeFile).where(col(KnowledgeFile.id).in_(file_ids))

        statement = statement.values(status=status.value)

        if remark:
            statement = statement.values(remark=remark)

        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    def filter_file_by_metadata_fields(
        cls, knowledge_id: int, logical: Literal["and", "or"], metadata_filters: list[dict[str, dict[str, Any]]]
    ) -> list[int]:
        """Filter knowledge files based on user-defined metadata fields.

        MySQL: builds a raw SQL WHERE clause using the sql_key from each filter,
        which may contain MySQL JSON path expressions like JSON_UNQUOTE(JSON_EXTRACT(...)).

        DaMeng/others: fetches all files for the knowledge and filters in Python
        using the py_field tuple stored alongside each filter entry.
        """
        with get_sync_db_session() as session:
            dialect = session.bind.dialect.name if session.bind else "mysql"

            if dialect == "mysql":
                return cls._filter_sql(session, knowledge_id, logical, metadata_filters)
            return cls._filter_python(session, knowledge_id, logical, metadata_filters)

    @classmethod
    def _filter_sql(cls, session, knowledge_id: int, logical: str, metadata_filters: list[dict]) -> list[int]:
        """MySQL path: inject SQL expressions directly into the WHERE clause."""
        statement = "select id from knowledgefile where knowledge_id = :knowledge_id and "
        params = {"knowledge_id": knowledge_id}
        params_index = 1
        field_statement = []
        for metadata_filter in metadata_filters:
            for key, key_info in metadata_filter.items():
                key_comparison = key_info["comparison"]
                key_value = key_info["value"]
                extra_filter = key_info.get("extra_filter")
                if key_value is not None:
                    params_key = f"tmp_params_{params_index}"
                    params[params_key] = key_value
                    sub_statement = f"{key} {key_comparison} :{params_key}"
                else:
                    sub_statement = f"{key} {key_comparison}"
                if extra_filter:
                    for sub_info in extra_filter:
                        params_index += 1
                        params_key = f"tmp_params_{params_index}"
                        params[params_key] = sub_info["value"]
                        sub_statement += f" AND {key} {sub_info['comparison']} :{params_key}"
                    sub_statement = f"({sub_statement})"
                field_statement.append(sub_statement)
                params_index += 1
        field_statement = f" {logical} ".join(field_statement)
        statement += f"({field_statement})"
        file_ids = []
        result = session.execute(text(statement), params)
        for one in result:
            file_ids.append(one[0])
        return file_ids

    @classmethod
    def _filter_python(cls, session, knowledge_id: int, logical: str, metadata_filters: list[dict]) -> list[int]:
        """DaMeng/others: fetch all files and apply filters in Python.

        Each filter entry must have a 'py_field' key in its value dict that
        specifies how to retrieve the value from the file object:
          - str: attribute name on KnowledgeFileDao (preset fields)
          - tuple ('user_metadata', field_name): nested JSON lookup
        """
        from sqlmodel import select as _select

        rows = session.exec(_select(KnowledgeFileDao).where(KnowledgeFileDao.knowledge_id == knowledge_id)).all()

        file_ids = []
        for file in rows:
            results = []
            for metadata_filter in metadata_filters:
                for key, key_info in metadata_filter.items():
                    py_field = key_info.get("py_field", key)
                    target_value = key_info["value"]
                    comparison = key_info["comparison"]
                    extra_filter = key_info.get("extra_filter")

                    # Resolve actual value from file
                    if isinstance(py_field, tuple) and py_field[0] == "user_metadata":
                        field_name = py_field[1]
                        meta = file.user_metadata or {}
                        field_data = meta.get(field_name, {})
                        actual = field_data.get("field_value") if isinstance(field_data, dict) else None
                    else:
                        actual = getattr(file, py_field, None)
                        if actual is not None:
                            actual = str(actual)

                    match = cls._compare(actual, comparison, target_value)
                    if match and extra_filter:
                        for sub_info in extra_filter:
                            if not cls._compare(actual, sub_info["comparison"], sub_info["value"]):
                                match = False
                                break
                    results.append(match)

            matched = all(results) if logical.lower() == "and" else any(results)
            if matched:
                file_ids.append(file.id)
        return file_ids

    @staticmethod
    def _compare(actual, op: str, target) -> bool:
        if actual is None:
            return op in ("!=", "<>") and target is not None
        try:
            a, t = float(actual), float(target)
            if op == "=":
                return a == t
            if op == "!=":
                return a != t
            if op == "<>":
                return a != t
            if op == ">":
                return a > t
            if op == "<":
                return a < t
            if op == ">=":
                return a >= t
            if op == "<=":
                return a <= t
        except (TypeError, ValueError):
            pass
        s_actual, s_target = str(actual), str(target) if target is not None else ""
        if op == "=":
            return s_actual == s_target
        if op in ("!=", "<>"):
            return s_actual != s_target
        return False

    @classmethod
    async def aget_files_by_similar_status(
        cls,
        knowledge_id: int,
        similar_status: int,
    ) -> list["KnowledgeFile"]:
        """Files in a space whose similar_status equals the given value.

        Only parsed-SUCCESS files are returned — pending similar UI shouldn't surface
        files that aren't yet usable.
        """
        statement = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.similar_status == similar_status,
            KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
        )
        async with get_async_db_session() as session:
            result = await session.execute(statement)
            return list(result.scalars().all())

    @classmethod
    def update_file_updater(cls, file_id: int, updater_id: int, updater_name: str) -> None:
        """
        Update Knowledge File Updater Information
        :param file_id: Knowledge DocumentsID
        :param updater_id: User who updated  ID
        :param updater_name: Updated By Username
        :return: None
        """

        statement = update(KnowledgeFile).where(col(KnowledgeFile.id) == file_id)

        statement = statement.values(updater_id=updater_id, updater_name=updater_name)
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()


class QAKnoweldgeDao(QAKnowledgeBase):
    @classmethod
    def get_qa_knowledge_by_knowledge_id(cls, knowledge_id: int, page: int, page_size: int):
        offset = (page - 1) * page_size
        state = (
            select(QAKnowledge)
            .where(
                QAKnowledge.knowledge_id == knowledge_id,
            )
            .offset(offset)
            .limit(page_size)
        )
        with get_sync_db_session() as session:
            return session.exec(state).all()

    @classmethod
    def get_qa_knowledge_by_knowledge_ids(cls, knowledge_ids: list[int]) -> list[QAKnowledge]:
        with get_sync_db_session() as session:
            return session.exec(select(QAKnowledge).where(QAKnowledge.knowledge_id.in_(knowledge_ids))).all()

    @classmethod
    async def aget_qa_knowledge_by_knowledge_ids(cls, knowledge_ids: list[int]) -> list[QAKnowledge]:
        async with get_async_db_session() as session:
            result = await session.exec(select(QAKnowledge).where(col(QAKnowledge.knowledge_id).in_(knowledge_ids)))
            return result.all()

    @classmethod
    def get_qa_knowledge_by_primary_id(cls, qa_id: int) -> QAKnowledge:
        with get_sync_db_session() as session:
            return session.exec(select(QAKnowledge).where(QAKnowledge.id == qa_id)).first()

    @classmethod
    def get_qa_knowledge_by_name(cls, question: list[str], knowledge_id: int, exclude_id: int = None) -> QAKnowledge:
        from bisheng.core.database.dialect_helpers import json_array_contains

        with get_sync_db_session() as session:
            dialect = session.bind.dialect.name if session.bind else "mysql"
            group_filters = []
            for one in question:
                group_filters.append(json_array_contains(QAKnowledge.questions, json.dumps(one), dialect))
            statement = select(QAKnowledge).where(or_(*group_filters)).where(QAKnowledge.knowledge_id == knowledge_id)
            if exclude_id:
                statement = statement.where(QAKnowledge.id != exclude_id)
            return session.exec(statement).first()

    @classmethod
    def update(cls, qa_knowledge: QAKnowledge):
        if qa_knowledge.id is None:
            raise ValueError("idTidak boleh kosong.")
        with get_sync_db_session() as session:
            session.add(qa_knowledge)
            session.commit()
            session.refresh(qa_knowledge)
        return qa_knowledge

    @classmethod
    def delete_batch(cls, qa_ids: list[int]) -> bool:
        with get_sync_db_session() as session:
            session.exec(delete(QAKnowledge).where(QAKnowledge.id.in_(qa_ids)))
            session.commit()
            return True

    @classmethod
    def select_list(cls, ids: list[int]) -> list[QAKnowledge]:
        with get_sync_db_session() as session:
            QAKnowledges = session.exec(select(QAKnowledge).where(QAKnowledge.id.in_(ids))).all()
        if not QAKnowledges:
            raise ValueError("Knowledge base does not exist")
        return QAKnowledges

    @classmethod
    def insert_qa(cls, qa_knowledge: QAKnowledgeUpsert):
        with get_sync_db_session() as session:
            qa = QAKnowledge.model_validate(qa_knowledge)
            session.add(qa)
            session.commit()
            session.refresh(qa)
        return qa

    @classmethod
    def batch_insert_qa(cls, qa_knowledges: list[QAKnowledgeUpsert]) -> list[QAKnowledge]:
        with get_sync_db_session() as session:
            qas = []
            for qa_knowledge in qa_knowledges:
                qa = QAKnowledge.model_validate(qa_knowledge)
                qas.append(qa)
            session.add_all(qas)
            session.commit()
            for qa in qas:
                session.refresh(qa)
            return qas

    @classmethod
    async def total_count(cls, sql):
        async with get_async_db_session() as session:
            return await async_get_count(session, sql)

    @classmethod
    async def query_by_condition(cls, sql):
        async with get_async_db_session() as session:
            result = await session.exec(sql)
            return result.all()

    @classmethod
    def query_by_condition_v1(cls, source: list[int], create_start: str, create_end: str):
        with get_sync_db_session() as session:
            sql = (
                select(QAKnowledge)
                .where(QAKnowledge.source.in_(source))
                .where(QAKnowledge.create_time.between(create_start, create_end))
            )

            return session.exec(sql).all()

    # accordingqa_idTotal Fetched
    @classmethod
    async def async_count_by_id(cls, qa_id: int) -> int:
        async with get_async_db_session() as session:
            statement = select(func.count(QAKnowledge.id)).where(QAKnowledge.knowledge_id == qa_id)
            return await async_get_count(session, statement)

    @classmethod
    def count_by_id(cls, qa_id: int) -> int:
        with get_sync_db_session() as session:
            statement = select(func.count(QAKnowledge.id)).where(QAKnowledge.knowledge_id == qa_id)
            return get_count(session, statement)

    @classmethod
    def batch_update_status_by_ids(cls, qa_ids: list[int], status: QAStatus, remark: str = "") -> None:
        """
        accordingQAkey learning pointsIDBulk Update Status
        :param qa_ids: QAkey learning pointsIDVertical
        :param status: Status
        :param remark: Remark
        :return:
        """

        statement = update(QAKnowledge).where(col(QAKnowledge.id).in_(qa_ids))

        statement = statement.values(status=status.value).values(remark=remark)
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()

    # according knowledge_id Update status
    @classmethod
    def update_status_by_knowledge_id(cls, knowledge_id: int, status: QAStatus, remark: str = "") -> None:
        """
        according knowledge_id Update status
        :param knowledge_id: The knowledge base uponID
        :param status: Status
        :param remark: Remark
        :return:
        """

        statement = update(QAKnowledge).where(col(QAKnowledge.knowledge_id) == knowledge_id)

        statement = statement.values(status=status.value).values(remark=remark)
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()


# ─── Space Folder / File helpers (Space-scoped operations on KnowledgeFile) ──
