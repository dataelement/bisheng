from dataclasses import dataclass
from enum import Enum
from typing import List

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
class PipelineResult:
    stage_reached: PipelineStage
    documents: List[Document]
    duration_seconds: float


class TextBbox(BaseModel):
    content: str = ""
    type: str = Field(default="text", description="text type")
    part_id: str = ""
    bbox: List[float] = Field(default_factory=list)
    page: int = 1
