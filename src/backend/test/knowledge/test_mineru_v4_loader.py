import json
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bisheng.knowledge.rag.pipeline.loader.mineru_v4 import MineruV4Loader
from bisheng.knowledge.rag.pipeline.loader.mineru_v4_client import MineruV4Error
from bisheng.knowledge.rag.pipeline.transformer.extra_file import ExtraFileTransformer
from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer


@pytest.fixture(autouse=True)
def mock_minio_bucket(monkeypatch):
    monkeypatch.setattr(MineruV4Loader, "_minio_bucket", property(lambda self: "test-bucket"))


def _middle_json():
    return {
        "schema": "docvortex.middle",
        "schema_version": "2.0",
        "is_full_document": True,
        "metadata": {"file_suffix": "pdf", "producer": {"name": "mineru", "version": "4.0.0"}},
        "extensions": {"docvortex_layout": {"pages": [{"page_idx": 0, "width_pt": 200, "height_pt": 100}]}},
        "pages": [
            {
                "page_idx": 0,
                "blocks": [
                    {
                        "type": "doc_title",
                        "index": 0,
                        "bbox": [0.1, 0.1, 0.9, 0.2],
                        "content": [{"type": "text", "content": "Report"}],
                    },
                    {
                        "type": "text",
                        "index": 1,
                        "bbox": [0.1, 0.3, 0.9, 0.4],
                        "content": [
                            {"type": "text", "content": "Value "},
                            {"type": "equation_inline", "content": "x^2"},
                        ],
                    },
                    {
                        "type": "image",
                        "index": 2,
                        "bbox": [0.2, 0.5, 0.6, 0.8],
                        "content": [
                            {
                                "type": "image_body",
                                "index": 2,
                                "image_path": "images/page_0_image_2.png",
                                "content": "",
                            },
                            {"type": "image_caption", "index": 3, "content": [{"type": "text", "content": "Chart"}]},
                        ],
                    },
                ],
            }
        ],
    }


def _zip(tmp_path, middle=None, image=b"image", member_name="images/page_0_image_2.png"):
    result = tmp_path / "result.zip"
    with zipfile.ZipFile(result, "w") as archive:
        archive.writestr("middle_json.json", json.dumps(middle or _middle_json()))
        if image is not None:
            archive.writestr(member_name, image)
    return result


def _loader(tmp_path, *, retain_images=True):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-test")
    return MineruV4Loader(
        file_path=str(source),
        file_metadata={"source": "test"},
        file_extension="pdf",
        tmp_dir=str(tmp_path),
        image_object_dir="kb/1/images",
        api_url="https://mineru.example",
        retain_images=retain_images,
    )


def test_loader_preserves_text_equation_image_bbox_and_indexes(tmp_path):
    loader = _loader(tmp_path)
    result = _zip(tmp_path)
    with patch.object(loader.client, "parse", return_value=str(result)):
        document = loader.load()[0]
    text = document.page_content
    assert "Report" in text
    assert "$x^2$" in text
    assert "Chart" in text
    assert "page_0_image_2.png" in text
    assert "/test-bucket/kb/1/images/page_0_image_2.png" in text
    assert len(loader.bbox_list) == 3
    assert loader.bbox_list[0].bbox == [20, 10, 180, 20]
    assert document.metadata["pages"] == [0, 0, 0]
    for start, end in document.metadata["indexes"]:
        assert text[start:end].strip()
    assert (tmp_path / "images" / "page_0_image_2.png").read_bytes() == b"image"


def test_fractional_bbox_matches_saved_labels_after_splitting(tmp_path):
    loader = _loader(tmp_path)
    middle = _middle_json()
    middle["extensions"]["docvortex_layout"]["pages"][0].update(width_pt=595.32, height_pt=841.92)
    block = middle["pages"][0]["blocks"][0]
    block["bbox"] = [0.1234, 0.2345, 0.8765, 0.3456]
    middle["pages"][0]["blocks"] = [block]
    result = _zip(tmp_path, middle=middle, image=None)
    with patch.object(loader.client, "parse", return_value=str(result)):
        documents = loader.load()

    expected = [73, 197, 521, 290]
    assert documents[0].metadata["bboxes"] == [expected]
    assert all(type(value) is int for value in documents[0].metadata["bboxes"][0])
    assert loader.bbox_list[0].bbox == expected

    chunks = SplitterTransformer(separator=["\n\n"], chunk_size=1000, chunk_overlap=0).transform_documents(documents)
    knowledge_file = SimpleNamespace(bbox_object_name="")
    with (
        patch("bisheng.knowledge.rag.pipeline.transformer.extra_file.get_minio_storage_sync") as get_minio,
        patch(
            "bisheng.knowledge.rag.pipeline.transformer.extra_file.KnowledgeUtils.get_knowledge_bbox_file_object_name",
            return_value="bbox/1.json",
            create=True,
        ),
    ):
        ExtraFileTransformer(loader, "1", 1, knowledge_file=knowledge_file).transform_documents(chunks)
    saved_labels = json.loads(get_minio.return_value.put_object_sync.call_args.kwargs["file"])
    chunk_boxes = json.loads(chunks[0].metadata["bbox"])["chunk_bboxes"]
    assert chunk_boxes == [{"page": 0, "bbox": expected}]
    for box in chunk_boxes:
        label_id = "-".join(map(str, [box["page"], *box["bbox"]]))
        assert label_id in saved_labels
        assert saved_labels[label_id]["bbox"] == box["bbox"]


@pytest.mark.parametrize(
    "change",
    [
        {"schema": "docvortex.model"},
        {"schema_version": "1.0"},
        {"pages": []},
    ],
)
def test_loader_rejects_invalid_or_empty_middle_json(tmp_path, change):
    loader = _loader(tmp_path)
    result = _zip(tmp_path, middle={**_middle_json(), **change})
    with patch.object(loader.client, "parse", return_value=str(result)), pytest.raises(MineruV4Error):
        loader.load()


def test_loader_rejects_missing_image(tmp_path):
    loader = _loader(tmp_path)
    result = _zip(tmp_path, image=None)
    with patch.object(loader.client, "parse", return_value=str(result)), pytest.raises(MineruV4Error, match="image"):
        loader.load()


def test_loader_rejects_unsafe_zip_member(tmp_path):
    loader = _loader(tmp_path)
    result = _zip(tmp_path, member_name="../escape.png")
    with patch.object(loader.client, "parse", return_value=str(result)), pytest.raises(MineruV4Error, match="ZIP"):
        loader.load()


def test_loader_rewrites_dot_relative_image_and_rejects_flatten_collision(tmp_path):
    loader = _loader(tmp_path)
    middle = _middle_json()
    middle["pages"][0]["blocks"][2]["content"][0]["image_path"] = "./images/page_0_image_2.png"
    result = _zip(tmp_path, middle=middle)
    with patch.object(loader.client, "parse", return_value=str(result)):
        text = loader.load()[0].page_content
    assert "./images" not in text
    assert "![image](/test-bucket/kb/1/images/page_0_image_2.png)" in text

    with zipfile.ZipFile(result, "a") as archive:
        archive.writestr("images/sub/page_0_image_2.png", b"collision")
    with (
        patch.object(loader.client, "parse", return_value=str(result)),
        pytest.raises(MineruV4Error, match="duplicated"),
    ):
        loader.load()


@pytest.mark.parametrize("prefix", ["images", "./images"])
def test_loader_rewrites_nested_image_member(tmp_path, prefix):
    loader = _loader(tmp_path)
    middle = _middle_json()
    middle["pages"][0]["blocks"][2]["content"][0]["image_path"] = f"{prefix}/sub/figure.png"
    result = _zip(tmp_path, middle=middle, member_name="images/sub/figure.png")
    with patch.object(loader.client, "parse", return_value=str(result)):
        text = loader.load()[0].page_content
    assert "![image](/test-bucket/kb/1/images/figure.png)" in text
    assert "images/sub/figure.png" not in text
    assert (tmp_path / "images" / "figure.png").read_bytes() == b"image"


@pytest.mark.parametrize("image", [b"image", None])
def test_loader_omits_image_refs_when_retention_disabled(tmp_path, image):
    loader = _loader(tmp_path, retain_images=False)
    middle = _middle_json()
    middle["pages"][0]["blocks"][1]["content"].append(
        {"type": "text", "content": " with ![inline](images/sub/figure.png) and more text"}
    )
    middle["pages"][0]["blocks"][2]["content"][0]["image_path"] = "images/sub/figure.png"
    result = _zip(tmp_path, middle=middle, image=image, member_name="images/sub/figure.png")
    with patch.object(loader.client, "parse", return_value=str(result)):
        document = loader.load()[0]
    assert "Report" in document.page_content
    assert "Chart" in document.page_content
    assert "more text" in document.page_content
    assert "![" not in document.page_content
    assert "images/" not in document.page_content
    assert loader.local_image_dir is None
    assert not (tmp_path / "images").exists()
    assert all(document.page_content[start:end].strip() for start, end in document.metadata["indexes"])


def test_loader_rejects_empty_path_segment(tmp_path):
    loader = _loader(tmp_path)
    result = _zip(tmp_path, member_name="images//page_0_image_2.png")
    with patch.object(loader.client, "parse", return_value=str(result)), pytest.raises(MineruV4Error, match="ZIP"):
        loader.load()


def test_loader_preserves_table_equation_and_multiple_images(tmp_path):
    loader = _loader(tmp_path)
    middle = _middle_json()
    blocks = middle["pages"][0]["blocks"]
    blocks.append(
        {
            "type": "table",
            "bbox": [0.1, 0.1, 0.9, 0.8],
            "content": [{"type": "table_body", "content": '<table><tr class="row"><td>A</td><td>B</td></tr></table>'}],
        }
    )
    blocks.append({"type": "equation", "bbox": [0.1, 0.1, 0.9, 0.8], "content": "x+y"})
    blocks.append(
        {
            "type": "image",
            "bbox": [0.1, 0.1, 0.9, 0.8],
            "content": [{"type": "image_body", "image_path": "images/second.png", "content": ""}],
        }
    )
    result = _zip(tmp_path, middle=middle)
    with zipfile.ZipFile(result, "a") as archive:
        archive.writestr("images/second.png", b"second")
    with patch.object(loader.client, "parse", return_value=str(result)):
        text = loader.load()[0].page_content
    assert "| A | B |" in text
    assert "$$x+y$$" in text
    assert text.count("![image]") == 2
    assert (tmp_path / "images" / "second.png").read_bytes() == b"second"
