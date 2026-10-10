"""LocalPdfLoader must emit splitter-aligned bbox metadata for PDF citations."""

import json

import fitz

from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
from bisheng.knowledge.rag.pipeline.loader.pdf import LocalPdfLoader
from bisheng.knowledge.rag.pipeline.loader.utils.md_from_pdf import align_pdf_elements
from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer


def test_align_pdf_elements_covers_rewritten_image_and_text():
    content = "Hello world\n\n![image_1_1.png](/bucket/dir/image_1_1.png)\n\n"
    elements = [
        {
            "type": "text",
            "page": 0,
            "bbox": [10.0, 20.0, 110.0, 40.0],
            "content": "Hello world",
        },
        {
            "type": "image",
            "page": 0,
            "bbox": [12.0, 50.0, 200.0, 180.0],
            "content": "![image_1_1.png](/tmp/images/image_1_1.png)",
            "image_filename": "image_1_1.png",
        },
    ]

    layout = align_pdf_elements(content, elements)

    assert layout["pages"] == [0, 0]
    assert layout["types"] == ["text", "image"]
    assert layout["indexes"][0] == [0, len("Hello world") - 1]
    image_start = content.find("![image_1_1.png]")
    image_end = content.find(")", image_start)
    assert layout["indexes"][1] == [image_start, image_end]
    assert layout["bboxes"][1] == [12.0, 50.0, 200.0, 180.0]


def test_align_pdf_elements_drops_images_when_not_retained():
    content = "Only text left"
    elements = [
        {
            "type": "image",
            "page": 0,
            "bbox": [0, 0, 10, 10],
            "content": "![gone.png](/tmp/gone.png)",
            "image_filename": "gone.png",
        },
        {
            "type": "text",
            "page": 1,
            "bbox": [1, 2, 3, 4],
            "content": "Only text left",
        },
    ]

    layout = align_pdf_elements(content, elements, retain_images=False)

    assert layout["types"] == ["text"]
    assert layout["pages"] == [1]


def test_local_pdf_loader_splitter_keeps_chunk_bboxes(tmp_path):
    pdf_path = tmp_path / "hello.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello citation bbox")
    doc.save(str(pdf_path))
    doc.close()

    loader = LocalPdfLoader(
        file_path=str(pdf_path),
        file_metadata={"source": "hello.pdf"},
        file_extension="pdf",
        tmp_dir=str(tmp_path / "cache"),
    )
    documents = loader.load()
    assert len(documents) == 1
    assert documents[0].metadata.get("bboxes")
    assert documents[0].metadata.get("indexes")
    assert documents[0].metadata["pages"][0] == 0
    assert all(len(box) == 4 for box in documents[0].metadata["bboxes"])

    chunks = SplitterTransformer(
        separator=["\n\n", "\n", "。", "\\."],
        separator_rule=["after", "after", "after", "after"],
        chunk_size=1000,
        chunk_overlap=0,
    ).transform_documents(documents)

    assert chunks
    parsed = json.loads(chunks[0].metadata["bbox"])
    assert parsed["chunk_bboxes"]
    assert parsed["chunk_bboxes"][0]["bbox"]
    assert CitationRegistryService._extract_rag_bbox(chunks[0].metadata)


def test_local_pdf_loader_empty_placeholder_is_not_emitted(tmp_path):
    """Regression: empty chunk_bboxes used to serialize as {\"chunk_bboxes\": \"\"}."""
    pdf_path = tmp_path / "hello.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Keep this bbox")
    doc.save(str(pdf_path))
    doc.close()

    documents = LocalPdfLoader(
        file_path=str(pdf_path),
        file_metadata={},
        file_extension="pdf",
        tmp_dir=str(tmp_path / "cache"),
    ).load()
    chunks = SplitterTransformer(
        separator=["\n\n"],
        separator_rule=["after"],
        chunk_size=1000,
        chunk_overlap=0,
    ).transform_documents(documents)

    raw_bbox = chunks[0].metadata["bbox"]
    assert raw_bbox != json.dumps({"chunk_bboxes": ""})
    assert json.loads(raw_bbox)["chunk_bboxes"]
