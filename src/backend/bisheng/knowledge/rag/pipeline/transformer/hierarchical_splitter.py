import json
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.documents import BaseDocumentTransformer, Document

from bisheng.common.errcode.knowledge import KnowledgeFileChunkMaxError
from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer


class HierarchicalSplitterTransformer(BaseDocumentTransformer):
    _break_priority = ["\n", "。", "，", ",", "."]

    def __init__(
            self,
            hierarchy_level: int = 3,
            append_title: bool = False,
            max_chunk_size: int = 1000,
            fallback_separator: Optional[List[str]] = None,
            fallback_separator_rule: Optional[List[str]] = None,
            fallback_chunk_size: int = 1000,
            fallback_chunk_overlap: int = 0,
            max_chunk_limit: int = 10000,
    ) -> None:
        self.hierarchy_level = hierarchy_level
        self.append_title = append_title
        self.max_chunk_size = max_chunk_size
        self.max_chunk_limit = max_chunk_limit
        if not fallback_separator:
            fallback_separator = ["\n\n", "\n"]
        if not fallback_separator_rule:
            fallback_separator_rule = ["after" for _ in fallback_separator]
        self.fallback_splitter = SplitterTransformer(
            separator=fallback_separator,
            separator_rule=fallback_separator_rule,
            chunk_size=fallback_chunk_size,
            chunk_overlap=fallback_chunk_overlap,
        )

    def _split_long_text(self, text: str) -> List[str]:
        text = (text or "").strip()
        if not text:
            return []

        if len(text) <= self.max_chunk_size:
            return [text]

        segments: List[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= self.max_chunk_size:
                segments.append(remaining.strip())
                break

            window = remaining[:self.max_chunk_size]
            split_at = -1
            for token in self._break_priority:
                split_at = window.rfind(token)
                if split_at > 0:
                    split_at += len(token)
                    break

            if split_at <= 0:
                split_at = self.max_chunk_size

            segments.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].lstrip()
        return [one for one in segments if one]

    def _build_nav_prefix(self, nav_path: List[str]) -> str:
        nav_prefix = ""
        for one_index, one in enumerate(nav_path):
            nav_prefix += self._format_markdown_heading(one, one_index + 1) + "\n"
        return nav_prefix

    @staticmethod
    def _format_markdown_heading(title: str, level: int) -> str:
        heading_level = max(1, min(level, 6))
        return "#" * heading_level + f" {title.strip()}"

    def _normalize_metadata(self, metadata: Dict, chunk_index: int) -> Dict:
        new_metadata = metadata.copy()
        new_metadata["chunk_index"] = chunk_index
        new_metadata["bbox"] = json.dumps({"chunk_bboxes": new_metadata.get("chunk_bboxes", "")})
        if "page" not in new_metadata:
            new_metadata["page"] = 0
        if len(new_metadata.get("nav_path") or []) == 0:
            new_metadata["nav_path"] = None
            new_metadata["nav_depth"] = 0
        if len(new_metadata.get("nav_path") or []) > self.hierarchy_level:
            new_metadata["nav_path"] = new_metadata["nav_path"][:self.hierarchy_level]
            new_metadata["nav_depth"] = len(new_metadata["nav_path"])
        if "is_heading" not in new_metadata:
            new_metadata["is_heading"] = False
        return new_metadata

    def transform_documents(
            self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        if not documents:
            return documents

        if any(doc.metadata.get("hierarchical_fallback") for doc in documents):
            fallback_text = "\n\n".join([doc.page_content for doc in documents if doc.page_content])
            fallback_metadata = documents[0].metadata.copy()
            fallback_metadata.pop("hierarchical_fallback", None)
            fallback_doc = Document(page_content=fallback_text, metadata=fallback_metadata)
            return self.fallback_splitter.transform_documents([fallback_doc])

        merged_blocks: List[Dict] = []
        for doc in documents:
            metadata = doc.metadata.copy()
            original_nav_path = list(metadata.get("nav_path") or [])
            nav_path = list(original_nav_path)
            if nav_path:
                nav_path = nav_path[:self.hierarchy_level]
            is_heading = bool(metadata.get("is_heading", False))
            text = (doc.page_content or "").strip()

            if is_heading:
                if self.append_title and len(original_nav_path) > self.hierarchy_level and text:
                    merged_blocks.append({
                        "nav_path": nav_path,
                        "text": self._format_markdown_heading(text, len(original_nav_path)),
                        "metadata": metadata,
                    })
                continue

            if not text:
                continue

            if merged_blocks and merged_blocks[-1]["nav_path"] == nav_path:
                merged_blocks[-1]["text"] += f"\n\n{text}"
                continue

            merged_blocks.append({
                "nav_path": nav_path,
                "text": text,
                "metadata": metadata,
            })

        if not merged_blocks:
            fallback_doc = Document(page_content=documents[0].page_content, metadata=documents[0].metadata.copy())
            return self.fallback_splitter.transform_documents([fallback_doc])

        result: List[Document] = []
        for block in merged_blocks:
            nav_path = block["nav_path"]
            block_text = block["text"].strip()
            for segment in self._split_long_text(block_text):
                if self.append_title and nav_path:
                    prefix = self._build_nav_prefix(nav_path)
                    final_text = f"{prefix}\n{segment}".strip()
                else:
                    final_text = segment

                metadata = block["metadata"].copy()
                metadata["nav_path"] = nav_path or None
                metadata["nav_depth"] = len(nav_path)
                metadata["is_heading"] = False
                result.append(Document(page_content=final_text, metadata=metadata))

        for index, one in enumerate(result):
            one.metadata = self._normalize_metadata(one.metadata, index)
            if len(one.page_content) > self.max_chunk_limit:
                raise KnowledgeFileChunkMaxError()

        return result
