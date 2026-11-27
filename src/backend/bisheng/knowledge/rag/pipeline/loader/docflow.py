"""DocFlow loader: parsing only; the existing pipeline owns ingestion."""

import asyncio

from langchain_core.documents import Document
from loguru import logger

from bisheng.knowledge.docflow.client import DocFlowError
from bisheng.knowledge.docflow.converter import CONVERTER_VERSION, convert_results
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.types import TextBbox


class DocFlowLoader(BaseBishengLoader):
    supports_semantic_markdown = True

    def __init__(self, filter_page_header_footer=False, *args, **kwargs):
        names = (
            "url",
            "host",
            "app_key",
            "app_secret",
            "docflow_app_id",
            "docflow_secret_code",
            "workspace_id",
            "parser_revision",
            "timeout",
            "poll_timeout",
            "poll_interval",
            "trust_env",
            "upload_headers",
            "max_concurrency",
        )
        self.config = {name: kwargs.pop(name) for name in names if name in kwargs}
        self.knowledge_file_id = kwargs.pop("knowledge_file_id", None)
        super().__init__(*args, **kwargs)
        self.filter_page_header_footer = filter_page_header_footer

    def load(self):
        from bisheng.core.context.tenant import get_current_tenant_id
        from bisheng.knowledge.domain.services.docflow_service import DocFlowService
        from bisheng.knowledge.domain.services.docflow_state import DocFlowState

        state = DocFlowState(get_current_tenant_id())
        service = DocFlowService(self.config, state)
        try:
            results = service.parse(self.file_path)
        finally:
            service.client.close()
        converted = convert_results(results, filter_page_header_footer=self.filter_page_header_footer)
        # Pixel coordinates align directly for images. For unrotated PDFs,
        # transform the actual OCR page dimensions into the original page rect.
        transforms = {}
        if self.file_extension == "pdf":
            import fitz

            with fitz.open(self.file_path) as pdf:
                pages = [page for file in results for page in file["document"]["pages"]]
                if len(pdf) != len(pages):
                    raise DocFlowError("DocFlow PDF page count differs from the source")
                for number, (source, page) in enumerate(zip(pdf, pages, strict=True), 1):
                    if source.rotation or page.get("angle", 0):
                        transforms[number] = None
                        logger.warning(
                            "DocFlow page {} rotation: preserve text without unverified PDF highlighting", number
                        )
                    else:
                        width, height = float(page.get("width", 0)), float(page.get("height", 0))
                        if width <= 0 or height <= 0:
                            raise DocFlowError("DocFlow PDF page dimensions are missing")
                        transforms[number] = (source.rect.width / width, source.rect.height / height)
        metadata = {**self.file_metadata, "page_base": 1, "indexes": [], "bboxes": [], "pages": [], "types": []}
        self.bbox_list = []
        for number, span in enumerate(converted.spans):
            bbox = list(span["bbox"])
            if self.file_extension == "pdf":
                scale = transforms[span["page"]]
                if scale is None:
                    continue
                bbox = [value * scale[index % 2] for index, value in enumerate(bbox)]
            metadata["indexes"].append([span["start"], span["end"]])
            metadata["bboxes"].append(bbox)
            metadata["pages"].append(span["page"])
            metadata["types"].append(span["type"])
            self.bbox_list.append(
                TextBbox(text=span["text"], type=span["type"], part_id=str(number), bbox=bbox, page=span["page"])
            )
        for warning in sorted(set(converted.warnings)):
            logger.warning("DocFlow conversion: {}", warning)
        return [Document(page_content=converted.text, metadata=metadata)]

    async def aload(self):
        return await asyncio.to_thread(self.load)

    def ingest_documents(self, documents, stores):
        if not stores:
            return
        if self.knowledge_file_id is None:
            # Workflow temporary collections use their existing lifecycle and
            # UUID document identifiers, not knowledge-file ingestion checkpoints.
            for store in stores:
                store.add_documents(documents)
            return
        from bisheng.core.context.tenant import get_current_tenant_id
        from bisheng.knowledge.domain.services.docflow_ingest import DocFlowIngest
        from bisheng.knowledge.domain.services.docflow_state import DocFlowState

        state = DocFlowState(get_current_tenant_id())
        revision = f"{CONVERTER_VERSION}:{self.config.get('parser_revision', '1')}"
        return DocFlowIngest(state, cache_revision=revision).run(documents, stores)
