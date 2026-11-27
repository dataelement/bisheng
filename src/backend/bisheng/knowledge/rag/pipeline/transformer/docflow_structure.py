"""Heading-aware OCR sections using the existing character splitter and bbox contract."""

import re
from itertools import pairwise

from langchain_core.documents import BaseDocumentTransformer, Document

from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer


class DocFlowStructureSplitter(BaseDocumentTransformer):
    def __init__(self, hierarchy_level=3, append_title=False, **kwargs):
        self.level = hierarchy_level
        self.append_title = append_title
        if not kwargs.get("separator"):
            kwargs["separator"] = ["\n\n", "\n", ""]
            kwargs["separator_rule"] = ["after"] * 3
        self.splitter = SplitterTransformer(**kwargs)

    def transform_documents(self, documents, **kwargs):
        sections = []
        for document in documents:
            text = document.page_content
            headings = list(re.finditer(r"^(#{1,6})[ \t]+(.+)$", text, re.MULTILINE))
            boundaries = sorted({0, len(text), *(heading.start() for heading in headings)})
            path = []
            for start, end in pairwise(boundaries):
                section_text = text[start:end]
                heading = next((heading for heading in headings if heading.start() == start), None)
                if heading:
                    depth = len(heading.group(1))
                    path = [*path[: depth - 1], heading.group(2).strip()]
                if not section_text.strip():
                    continue
                prefix = ""
                if self.append_title and path:
                    # Prefix only the ancestors; the section already includes its
                    # own heading. Generated title text carries no invented bbox.
                    prefix = "\n".join(
                        "#" * (index + 1) + " " + title for index, title in enumerate(path[:-1][: self.level])
                    )
                    if prefix:
                        prefix += "\n\n"
                metadata = {
                    key: value
                    for key, value in document.metadata.items()
                    if key not in ("indexes", "pages", "bboxes", "types")
                }
                metadata.update(
                    indexes=[],
                    pages=[],
                    bboxes=[],
                    types=[],
                    nav_path=path[: self.level],
                    nav_depth=min(len(path), self.level),
                )
                original = document.metadata
                for index, interval in enumerate(original.get("indexes", [])):
                    left, right = max(start, interval[0]), min(end, interval[1])
                    if left < right:
                        metadata["indexes"].append([left - start + len(prefix), right - start + len(prefix)])
                        for name in ("pages", "bboxes", "types"):
                            metadata[name].append(original[name][index])
                sections.append(Document(page_content=prefix + section_text, metadata=metadata))
        chunks = self.splitter.transform_documents(sections)
        for index, chunk in enumerate(chunks):
            chunk.metadata["chunk_index"] = index
        return chunks
