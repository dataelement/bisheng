from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from langchain_core.documents import Document
from pydantic import BaseModel, Field


class PipelineStage(Enum):
    """定义 Pipeline 可停止的阶段"""

    LOAD = 1  # only load source document
    TRANSFORMER = 2  # stop after all transformations, but before embedding
    INGEST = 10  # full pipeline, including writing to vector store


@dataclass
class PipelineConfig:
    stop_at: PipelineStage = PipelineStage.INGEST


@dataclass
class ImageStorageContext:
    object_dir: str
    bucket_name: str
    url_builder: Callable[[str], str]
    before_upload: Callable[[list[str]], None] | None = None
    after_upload: Callable[[], None] | None = None
    rollback_on_failure: bool = False


@dataclass
class PipelineResult:
    stage_reached: PipelineStage
    documents: list[Document]
    duration_seconds: float


class TextBbox(BaseModel):
    text: str = ""
    type: str = Field(default="text", description="text type")
    part_id: str = ""
    bbox: list[float] = Field(default_factory=list)
    page: int = 1
