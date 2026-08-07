"""Request/response schemas for the F079 tag management console.

The console has two modes backed by two different tables:

- **Library mode** lists approved tags from ``tag`` and keys rows by ``tag.id``.
- **Review mode** lists pending/rejected tags from ``review_tag`` and keys rows by
  ``(name, resource_type)`` — see :class:`TagConsoleReviewRef` for why.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

MAX_PAGE_SIZE = 200
MAX_BATCH_SIZE = 500


class TagConsoleReviewStatus(str, Enum):
    PENDING = "pending"
    REJECTED = "rejected"


class TagConsoleSourceFile(BaseModel):
    """A knowledge file the tag is attached to.

    ``parent_id`` is the immediate folder, needed by the portal deep link that
    opens the containing folder before previewing the file.
    """

    file_id: int
    file_name: str
    knowledge_id: int
    parent_id: int | None = None


class TagConsoleFilter(BaseModel):
    """Filter fields shared by both modes."""

    tag_name: str | None = None
    resource_type: str | None = None
    submitter_id: int | None = None
    reviewer_id: int | None = None
    create_time_start: datetime | None = None
    create_time_end: datetime | None = None
    review_time_start: datetime | None = None
    review_time_end: datetime | None = None
    page: int = 1
    page_size: int = 20


# --------------------------------------------------------------------------
# Library mode — approved tags
# --------------------------------------------------------------------------


class TagConsoleSearchReq(TagConsoleFilter):
    """An empty ``library_ids`` means "every library visible to the caller"."""

    library_ids: list[int] = Field(default_factory=list)


class TagConsoleItem(BaseModel):
    """One approved tag.

    ``submitter_name`` is whoever originally proposed the tag: approving moves the
    row from ``review_tag`` into ``tag`` while preserving ``user_id``, so it stays
    the proposer rather than becoming the reviewer. For tags an admin added by
    hand it is simply the creator.
    """

    id: int
    name: str
    resource_type: str
    library_id: int | None = None
    library_name: str | None = None
    marked_knowledge_count: int = 0
    submitter_id: int | None = None
    submitter_name: str | None = None
    reviewer_id: int | None = None
    reviewer_name: str | None = None
    source_files: list[TagConsoleSourceFile] = Field(default_factory=list)
    create_time: datetime | None = None
    review_time: datetime | None = None


class TagConsoleSearchResp(BaseModel):
    data: list[TagConsoleItem]
    total: int


class TagConsoleCreateReq(BaseModel):
    tag_name: str
    library_id: int


class TagConsoleBatchDeleteReq(BaseModel):
    ids: list[int]


class TagConsoleBatchMoveReq(BaseModel):
    ids: list[int]
    target_library_id: int


# --------------------------------------------------------------------------
# Review mode — pending / rejected tags
# --------------------------------------------------------------------------


class TagConsoleReviewRef(BaseModel):
    """Identifies one review-mode row.

    A pending tag is identified by ``(name, resource_type)``, **not** by
    ``review_tag.id``: the same tag name produced in several knowledge spaces
    creates one ``review_tag`` row per space. The existing listing groups by
    ``(name, resource_type)`` and ``approve_or_reject_review_tag`` processes every
    row under that pair in one go. Keying by id would either show duplicate rows
    for one tag name, or let a single approval reach rows the user never selected.
    """

    name: str
    resource_type: str


class TagConsoleReviewItem(TagConsoleReviewRef):
    """One review-mode row, aggregating every ``review_tag`` under the pair."""

    status: TagConsoleReviewStatus
    review_tag_count: int = 0
    library_id: int | None = None
    library_name: str | None = None
    submitter_id: int | None = None
    submitter_name: str | None = None
    reviewer_id: int | None = None
    reviewer_name: str | None = None
    source_files: list[TagConsoleSourceFile] = Field(default_factory=list)
    create_time: datetime | None = None
    review_time: datetime | None = None
    reject_reason: str | None = None


class TagConsoleReviewSearchReq(TagConsoleFilter):
    """A ``None`` status means "pending and rejected together"."""

    status: TagConsoleReviewStatus | None = None


class TagConsoleReviewSearchResp(BaseModel):
    """``pending_count`` / ``rejected_count`` deliberately ignore the ``status``
    filter so the toolbar heading keeps showing both real totals even while the
    user is looking at one of them."""

    data: list[TagConsoleReviewItem]
    total: int
    pending_count: int
    rejected_count: int


class TagConsoleBatchApproveReq(BaseModel):
    items: list[TagConsoleReviewRef]
    target_library_id: int


class TagConsoleBatchRejectReq(BaseModel):
    items: list[TagConsoleReviewRef]
    reject_reason: str


# --------------------------------------------------------------------------
# Shared results
# --------------------------------------------------------------------------


class TagConsoleBatchFailure(BaseModel):
    name: str
    reason: str


class TagConsoleBatchResult(BaseModel):
    """Batch operations run item by item and never roll back as a whole: a tag
    another admin already handled must not undo the rest of the batch."""

    succeeded: int = 0
    skipped: int = 0
    failed: list[TagConsoleBatchFailure] = Field(default_factory=list)


class TagConsolePendingCountResp(BaseModel):
    pending_count: int
