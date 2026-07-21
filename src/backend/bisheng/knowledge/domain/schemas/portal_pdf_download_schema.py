from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class PortalPdfDownloadEntryPoint(str, Enum):
    SEARCH = "search"
    KNOWLEDGE_LIST = "knowledge_list"
    DETAIL = "detail"
    HOME_RECOMMENDATION = "home_recommendation"
    FAVORITE = "favorite"
    SHARE = "share"
    EXPERT_QA = "expert_qa"
    QA_CITATION = "qa_citation"
    BISHENG_KNOWLEDGE_LIST = "bisheng_knowledge_list"
    BISHENG_PREVIEW = "bisheng_preview"
    BISHENG_FAVORITE = "bisheng_favorite"
    BISHENG_VERSION_HISTORY = "bisheng_version_history"
    OTHER = "other"

    @classmethod
    def normalize(cls, value: object) -> PortalPdfDownloadEntryPoint:
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except (TypeError, ValueError):
            return cls.OTHER


class PortalPdfDownloadRequest(BaseModel):
    space_id: int = Field(..., gt=0)
    file_id: int = Field(..., gt=0)
    entry_point: PortalPdfDownloadEntryPoint = PortalPdfDownloadEntryPoint.OTHER
    share_access_grant: str = Field(default="", max_length=4096, exclude=True)

    @field_validator("entry_point", mode="before")
    @classmethod
    def normalize_entry_point(cls, value: object) -> PortalPdfDownloadEntryPoint:
        return PortalPdfDownloadEntryPoint.normalize(value)


class PortalShareDownloadGrantClaims(BaseModel):
    v: int = Field(default=1)
    purpose: str = Field(default="portal_share_pdf_download")
    aud: str = Field(default="shougang_portal")
    sub: str
    tenant_id: int = Field(..., gt=0)
    share_token: str = Field(..., min_length=1, max_length=256)
    space_id: int = Field(..., gt=0)
    file_id: int = Field(..., gt=0)
    allow_download: bool
    iat: int = Field(..., ge=0)
    exp: int = Field(..., gt=0)
    jti: str = Field(..., min_length=1, max_length=128)


@dataclass
class PreparedPortalPdfDownload:
    path: Path
    filename: str
    size: int
    cleanup_callback: Callable[[], Awaitable[None]] = field(repr=False)
    success_callback: Callable[[], Awaitable[None]] = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _success_recorded: bool = field(default=False, init=False, repr=False)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.cleanup_callback()

    async def _record_success_once(self) -> None:
        if self._success_recorded:
            return
        self._success_recorded = True
        try:
            await self.success_callback()
        except Exception:
            return

    async def iter_bytes(self, *, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        file_handle = None
        try:
            file_handle = self.path.open("rb")
            first_chunk = file_handle.read(chunk_size)
            if not first_chunk:
                return
            yield first_chunk
            await self._record_success_once()
            while chunk := file_handle.read(chunk_size):
                yield chunk
        finally:
            if file_handle is not None:
                file_handle.close()
            await self.close()
