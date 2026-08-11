"""Request/response schemas for the F079 tag management console.

The console has two modes backed by two different tables:

- **Library mode** lists approved tags from ``tag`` and keys rows by ``tag.id``.
- **Review mode** lists pending/rejected tags from ``review_tag`` and keys rows by
  ``(name, resource_type)`` — see :class:`TagConsoleReviewRef` for why.
"""

import re
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MAX_PAGE_SIZE = 200
MAX_BATCH_SIZE = 500


class TagConsoleReviewStatus(str, Enum):
    """Row status, plus one filter-only value.

    ``APPROVED`` rows do not live in ``review_tag`` at all — approving deletes
    the review row and writes the tag into ``tag`` — so they are read back from
    the tag library instead, recognised by a non-null ``reviewer_id``.

    ``REVIEWED`` is a *request* value only and never appears on a row: it is what
    the console's "已审核" tab asks for, meaning approved and rejected together.
    """

    PENDING = "pending"
    REJECTED = "rejected"
    APPROVED = "approved"
    REVIEWED = "reviewed"


class TagConsoleSourceFile(BaseModel):
    """A knowledge file the tag is attached to.

    ``parent_id`` is the immediate folder, needed by the portal deep link that
    opens the containing folder before previewing the file.
    """

    file_id: int
    file_name: str
    knowledge_id: int
    # 标签来源库 — the knowledge base the file lives in. Shown as its own column,
    # so the console does not have to resolve ids to names on the client.
    knowledge_name: str | None = None
    parent_id: int | None = None


class TagConsoleFilter(BaseModel):
    """Filter fields shared by both modes."""

    tag_name: str | None = None
    resource_type: str | None = None
    # 标签来源库: the knowledge space a tag was proposed from. Neither table
    # stores it, so it is matched through the tag's file links — which means a
    # tag an admin typed straight into a library has no source and can never
    # match this filter.
    source_knowledge_id: int | None = None
    submitter_id: int | None = None
    reviewer_id: int | None = None
    create_time_start: datetime | None = None
    create_time_end: datetime | None = None
    review_time_start: datetime | None = None
    review_time_end: datetime | None = None
    page: int = 1
    page_size: int = 20

    @field_validator("create_time_end", "review_time_end", mode="before")
    @classmethod
    def _end_of_day(cls, value):
        """A bare date as the upper bound means the end of that day.

        The filter bar sends ``YYYY-MM-DD``, which parses to midnight. Compared
        with ``<=`` that makes "从 8-11 到 8-11" match only rows stamped exactly
        00:00:00 — i.e. picking one day returned nothing. Widening it here rather
        than in the query keeps both listings and their counts consistent, and
        an explicit timestamp from any other caller is left alone.
        """
        if isinstance(value, str) and _DATE_ONLY.match(value.strip()):
            return f"{value.strip()}T23:59:59.999999"
        return value


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
    """The three counts deliberately ignore the ``status`` filter so the tab bar
    keeps showing real totals even while the user is looking at one of them."""

    data: list[TagConsoleReviewItem]
    total: int
    pending_count: int
    rejected_count: int
    approved_count: int = 0


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
