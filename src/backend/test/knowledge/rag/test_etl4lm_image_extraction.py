from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PIL import Image
from pydantic import ValidationError

from bisheng.core.config.settings import Etl4lmConf
from bisheng.knowledge.domain.models.knowledge_file import ParseType
from bisheng.knowledge.rag.base_file_pipeline import BaseFilePipeline
from bisheng.knowledge.rag.pipeline.loader.etl4lm import Etl4lmLoader


class _TestFilePipeline(BaseFilePipeline):
    @property
    def file_metadata(self) -> dict:
        return {}


def _partition(bbox: list[float], element_id: str = "figure-1") -> dict:
    return {
        "type": "Image",
        "text": "",
        "element_id": element_id,
        "metadata": {
            "extra_data": {
                "bboxes": [bbox],
                "pages": [0],
                "indexes": [[0, 0]],
                "types": ["image"],
            }
        },
    }


def _blank_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "input.pdf"
    document = fitz.open()
    document.new_page(width=400, height=300)
    document.save(pdf_path)
    document.close()
    return pdf_path


def _loader(tmp_path: Path, pdf_path: Path, file_extension: str = "pdf", **kwargs) -> Etl4lmLoader:
    return Etl4lmLoader(
        url="http://etl4lm.test",
        ocr_sdk_url="",
        file_path=str(pdf_path),
        file_metadata={},
        file_extension=file_extension,
        tmp_dir=str(tmp_path),
        **kwargs,
    )


def test_etl4lm_image_config_defaults_and_legacy_compatibility():
    config = Etl4lmConf()

    assert config.image_extraction_strategy == "original_first"
    assert config.image_fallback_dpi == 200
    assert config.image_max_pixels == 16_000_000
    assert Etl4lmConf.model_validate({"url": "http://etl4lm.test"}).url == "http://etl4lm.test"


@pytest.mark.parametrize(
    "values",
    [
        {"image_extraction_strategy": "unknown"},
        {"image_fallback_dpi": 71},
        {"image_fallback_dpi": 301},
        {"image_max_pixels": 999_999},
        {"image_max_pixels": 100_000_001},
    ],
)
def test_etl4lm_image_config_rejects_invalid_values(values: dict):
    with pytest.raises(ValidationError):
        Etl4lmConf.model_validate(values)


def test_base_pipeline_passes_file_retain_images_to_etl4lm(monkeypatch, tmp_path: Path):
    pipeline = object.__new__(_TestFilePipeline)
    pipeline.file_split_rule = SimpleNamespace(filter_page_header_footer=0, retain_images=0)
    pipeline.local_file_path = str(tmp_path / "input.pdf")
    pipeline.tmp_dir = str(tmp_path)
    pipeline.file_name = "input.pdf"
    monkeypatch.setattr(
        pipeline,
        "_get_loader_common_params",
        lambda: {
            "file_path": pipeline.local_file_path,
            "file_metadata": {},
            "file_extension": "pdf",
            "tmp_dir": pipeline.tmp_dir,
        },
    )
    knowledge_config = SimpleNamespace(
        loader_provider=ParseType.ETL4LM.value,
        etl4lm=Etl4lmConf(url="http://etl4lm.test"),
        mineru=SimpleNamespace(url=""),
        paddle_ocr=SimpleNamespace(url=""),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.rag.base_file_pipeline.settings.get_knowledge",
        lambda: knowledge_config,
    )

    loader = BaseFilePipeline._init_pdf_loader(pipeline)

    assert isinstance(loader, Etl4lmLoader)
    assert loader.retain_images is False


def test_render_only_extracts_high_resolution_image_without_changing_bbox(tmp_path: Path):
    pdf_path = _blank_pdf(tmp_path)
    bbox = [10, 20, 110, 70]
    partition = _partition(bbox)
    loader = _loader(
        tmp_path,
        pdf_path,
        image_extraction_strategy="render_only",
        image_fallback_dpi=200,
        image_max_pixels=16_000_000,
    )

    result = loader.extract_images([partition])

    assert result["figure-1"].endswith("figure-1.png")
    with Image.open(Path(result["figure-1"])) as image:
        assert image.width == pytest.approx(100 * 200 / 72, abs=2)
        assert image.height == pytest.approx(50 * 200 / 72, abs=2)
    assert partition["metadata"]["extra_data"]["bboxes"][0] == bbox


def test_rendered_image_keeps_existing_minio_url_contract(monkeypatch, tmp_path: Path):
    pdf_path = _blank_pdf(tmp_path)
    loader = _loader(
        tmp_path,
        pdf_path,
        image_object_dir="knowledge/images/10/20",
        image_extraction_strategy="render_only",
    )
    monkeypatch.setattr(Etl4lmLoader, "_minio_bucket", property(lambda self: "bucket"))

    result = loader.extract_images([_partition([10, 20, 110, 70])])

    assert result["figure-1"] == "/bucket/knowledge/images/10/20/figure-1.png"


def test_retain_images_false_skips_all_image_generation(tmp_path: Path):
    pdf_path = _blank_pdf(tmp_path)
    loader = _loader(tmp_path, pdf_path, retain_images=False)

    assert loader.extract_images([_partition([10, 20, 110, 70])]) == {}
    assert not (tmp_path / "images").exists()


def test_legacy_strategy_keeps_default_resolution_crop(tmp_path: Path):
    pdf_path = _blank_pdf(tmp_path)
    loader = _loader(tmp_path, pdf_path, image_extraction_strategy="legacy")

    result = loader.extract_images([_partition([10, 20, 110, 70])])

    with Image.open(Path(result["figure-1"])) as image:
        assert image.size == (100, 50)


def test_non_pdf_input_keeps_legacy_image_extraction(tmp_path: Path):
    image_path = tmp_path / "input.png"
    Image.new("RGB", (200, 100), color=(20, 80, 160)).save(image_path)
    loader = _loader(tmp_path, image_path, file_extension="png")

    result = loader.extract_images([_partition([10, 20, 110, 70])])

    assert (tmp_path / "pdf_page" / "0.png").exists()
    with Image.open(Path(result["figure-1"])) as image:
        assert image.size == (100, 50)


def test_image_settings_do_not_change_etl4lm_request_payload(monkeypatch, tmp_path: Path):
    pdf_path = _blank_pdf(tmp_path)
    loader = _loader(
        tmp_path,
        pdf_path,
        image_extraction_strategy="render_only",
        image_fallback_dpi=300,
        image_max_pixels=2_000_000,
    )
    captured_payload = {}

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"status_code": 200, "partitions": [], "text": "parsed"}

    def _post(url, json, timeout):
        captured_payload.update(json)
        return _Response()

    monkeypatch.setattr("bisheng.knowledge.rag.pipeline.loader.etl4lm.requests.post", _post)

    document = loader.load()[0]

    assert document.page_content == "parsed"
    assert "image_extraction_strategy" not in captured_payload
    assert "image_fallback_dpi" not in captured_payload
    assert "image_max_pixels" not in captured_payload
    assert captured_payload["b64_data"]
    assert captured_payload["mode"] == "partition"


def test_region_render_failure_propagates(monkeypatch, tmp_path: Path):
    pdf_path = _blank_pdf(tmp_path)
    loader = _loader(tmp_path, pdf_path, image_extraction_strategy="render_only")
    monkeypatch.setattr(
        fitz.Page,
        "get_pixmap",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("render failed")),
    )

    with pytest.raises(RuntimeError, match="render failed"):
        loader.extract_images([_partition([10, 20, 110, 70])])
