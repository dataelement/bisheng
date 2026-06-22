import re
import zipfile
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET

from loguru import logger

WORD_DOCUMENT_XML = "word/document.xml"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W_TEXT = f"{{{W_NS}}}t"
W_TEXTBOX_CONTENT = f"{{{W_NS}}}txbxContent"

_DOCX_NAMESPACES = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "v": "urn:schemas-microsoft-com:vml",
    "w": W_NS,
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
}

for prefix, uri in _DOCX_NAMESPACES.items():
    ET.register_namespace(prefix, uri)


def sanitize_docx_textbox_noise(doc_path: Path, output_dir: Path) -> Path:
    """Create a sanitized DOCX copy when textbox fallback content contains encoded noise."""
    if doc_path.suffix.lower() != ".docx":
        return doc_path

    try:
        with zipfile.ZipFile(doc_path) as source_archive:
            try:
                document_xml = source_archive.read(WORD_DOCUMENT_XML)
            except KeyError:
                return doc_path

            cleaned_xml, removed_count, removed_chars = _clean_document_xml(document_xml)
            if removed_count == 0:
                return doc_path

            output_dir.mkdir(parents=True, exist_ok=True)
            sanitized_path = output_dir / f"{doc_path.stem}.sanitized-{uuid4().hex}.docx"
            with zipfile.ZipFile(sanitized_path, "w", zipfile.ZIP_DEFLATED) as target_archive:
                for item in source_archive.infolist():
                    data = cleaned_xml if item.filename == WORD_DOCUMENT_XML else source_archive.read(item.filename)
                    target_archive.writestr(item, data)

            logger.info(
                f"Sanitized DOCX textbox fallback noise: file={doc_path}, "
                f"removed_count={removed_count}, removed_chars={removed_chars}"
            )
            return sanitized_path
    except (ET.ParseError, OSError, zipfile.BadZipFile) as exc:
        logger.warning(f"Skip DOCX textbox noise sanitization for {doc_path}: {exc}")
        return doc_path


def _clean_document_xml(document_xml: bytes) -> tuple[bytes, int, int]:
    root = ET.fromstring(document_xml)
    removed_count = 0
    removed_chars = 0

    for textbox in root.iter(W_TEXTBOX_CONTENT):
        for text_node in textbox.iter(W_TEXT):
            text = text_node.text or ""
            if _is_probable_encoded_noise(text):
                removed_count += 1
                removed_chars += len(text)
                text_node.text = ""

    if removed_count == 0:
        return document_xml, 0, 0

    cleaned_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return cleaned_xml, removed_count, removed_chars


def _is_probable_encoded_noise(text: str) -> bool:
    compact_text = "".join(text.split())
    if len(compact_text) < 512:
        return False

    if re.search(r"[\u4e00-\u9fff]", compact_text):
        return False

    allowed_chars = sum(1 for char in compact_text if char.isascii() and (char.isalnum() or char in "+/=_-"))
    if allowed_chars / len(compact_text) < 0.95:
        return False

    whitespace_count = sum(1 for char in text if char.isspace())
    if whitespace_count / len(text) > 0.02:
        return False

    alpha_count = sum(1 for char in compact_text if char.isalpha())
    return alpha_count / len(compact_text) > 0.2
