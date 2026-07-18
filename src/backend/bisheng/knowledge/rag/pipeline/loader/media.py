import os

from langchain_core.documents import Document

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services.media_transcription_service import (
    KnowledgeMediaTranscriptionService,
)
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader


class BishengMediaLoader(BaseBishengLoader):
    """Load audio/video files by transcribing speech to text."""

    def __init__(
        self,
        *args,
        knowledge_file: KnowledgeFile | None = None,
        media_kind: str = "audio",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.knowledge_file = knowledge_file
        self.media_kind = media_kind

    def load(self) -> list[Document]:
        result = KnowledgeMediaTranscriptionService.transcribe_media(
            self.file_path,
            source_file_name=self.file_metadata.get("document_name") or self.file_name,
            tenant_id=getattr(self.knowledge_file, "tenant_id", None),
        )
        preview_path = os.path.join(self.tmp_dir, f"{os.path.splitext(self.file_name)[0]}_transcript.md")
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(result.markdown)
        self.preview_file_path = preview_path

        metadata = self.file_metadata.copy()
        metadata["user_metadata"] = {
            **(metadata.get("user_metadata") or {}),
            "media_kind": self.media_kind,
            "transcription_model_id": result.model_id,
            "transcription_model_name": result.model_name,
        }

        if self.knowledge_file:
            self.knowledge_file.user_metadata = {
                **(self.knowledge_file.user_metadata or {}),
                "media_kind": self.media_kind,
                "transcription_model_id": result.model_id,
                "transcription_model_name": result.model_name,
            }

        return [Document(page_content=result.text, metadata=metadata)]
