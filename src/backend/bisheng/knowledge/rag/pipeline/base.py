import asyncio
import time
from abc import ABC, abstractmethod
from typing import List

from langchain_core.documents import BaseDocumentTransformer, Document
from langchain_core.vectorstores import VectorStore

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.types import PipelineStage, PipelineResult, PipelineConfig


class BasePipeline(ABC):
    def __init__(self,
                 loader: BaseBishengLoader = None,
                 transformers: List[BaseDocumentTransformer] = None,
                 vector_store: List[VectorStore] = None,
                 **kwargs):
        self.loader = loader
        self.transformers = transformers or []
        self.vector_store = vector_store or []

    @staticmethod
    def _make_result(stage: PipelineStage = PipelineStage.INGEST, docs: List[Document] = None,
                     start: float = 0) -> PipelineResult:
        result = PipelineResult(
            stage_reached=stage,
            documents=docs,
            duration_seconds=time.time() - start,
        )
        return result

    @abstractmethod
    def run(self, config: PipelineConfig = None) -> PipelineResult:
        pass

    async def arun(self, config: PipelineConfig = None) -> PipelineResult:
        return await asyncio.to_thread(self.run, config)


class NormalPipeline(BasePipeline):
    def run(self, config: PipelineConfig = None) -> PipelineResult:
        if config is None:
            config = PipelineConfig()

        start = time.time()
        # ① loader
        docs = self.loader.load()
        if config.stop_at == PipelineStage.LOAD:
            return self._make_result(stage=PipelineStage.LOAD, start=start)

        # transformer
        for transformer in self.transformers:
            docs = transformer.transform_documents(docs)
        if config.stop_at == PipelineStage.TRANSFORMER:
            return self._make_result(stage=PipelineStage.TRANSFORMER, docs=docs, start=start)

        # insert vector
        for vectorstore in self.vector_store:
            vectorstore.add_documents(docs)

        return self._make_result(stage=PipelineStage.INGEST, docs=docs, start=start)

    async def arun(self, config: PipelineConfig = None) -> PipelineResult:
        if config is None:
            config = PipelineConfig()

        start = time.time()
        docs = await self.loader.aload()
        if config.stop_at == PipelineStage.LOAD:
            return self._make_result(stage=PipelineStage.LOAD, docs=docs, start=start)

        for transformer in self.transformers:
            docs = await transformer.atransform_documents(docs)
        if config.stop_at == PipelineStage.TRANSFORMER:
            return self._make_result(stage=PipelineStage.TRANSFORMER, docs=docs, start=start)

        for vectorstore in self.vector_store:
            await vectorstore.aadd_documents(docs)

        return self._make_result(stage=PipelineStage.INGEST, docs=docs, start=start)
