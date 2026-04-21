import re
from typing import Dict, List, Sequence

from langchain_core.documents import Document


def _make_doc(text: str, metadata: Dict, nav_path: List[str], is_heading: bool) -> Document:
    one_metadata = metadata.copy()
    one_metadata["nav_path"] = list(nav_path)
    one_metadata["nav_depth"] = len(nav_path)
    one_metadata["is_heading"] = is_heading
    return Document(page_content=text.strip(), metadata=one_metadata)


def parse_markdown_to_hierarchical_documents(
        content: str,
        metadata: Dict,
        fallback_to_auto: bool = False,
) -> Sequence[Document]:
    normalized = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")

    documents: List[Document] = []
    current_path: List[str] = []
    paragraph_lines: List[str] = []
    has_heading = False
    in_code_block = False

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        paragraph = "\n".join(paragraph_lines).strip()
        paragraph_lines.clear()
        if paragraph:
            documents.append(_make_doc(paragraph, metadata, current_path, False))

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            paragraph_lines.append(line)
            idx += 1
            continue

        if not in_code_block:
            atx_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", stripped)
            if atx_match:
                flush_paragraph()
                has_heading = True
                depth = len(atx_match.group(1))
                title = atx_match.group(2).strip().rstrip("#").strip()
                current_path = current_path[:depth - 1] + [title]
                documents.append(_make_doc(title, metadata, current_path, True))
                idx += 1
                continue

            if idx + 1 < len(lines):
                underline = lines[idx + 1].strip()
                if stripped and re.fullmatch(r"=+", underline):
                    flush_paragraph()
                    has_heading = True
                    current_path = [stripped]
                    documents.append(_make_doc(stripped, metadata, current_path, True))
                    idx += 2
                    continue
                if stripped and re.fullmatch(r"-+", underline):
                    flush_paragraph()
                    has_heading = True
                    current_path = current_path[:1] + [stripped]
                    documents.append(_make_doc(stripped, metadata, current_path, True))
                    idx += 2
                    continue

        if stripped:
            paragraph_lines.append(line)
        else:
            flush_paragraph()
        idx += 1

    flush_paragraph()

    if has_heading or not fallback_to_auto:
        return documents

    fallback_metadata = metadata.copy()
    fallback_metadata["hierarchical_fallback"] = True
    return [Document(page_content=normalized.strip(), metadata=fallback_metadata)]
