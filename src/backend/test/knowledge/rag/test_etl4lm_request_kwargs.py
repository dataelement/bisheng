"""ETL4LM request customization through the knowledge configuration."""

from unittest.mock import Mock, patch

from bisheng.core.config.settings import Etl4lmConf
from bisheng.knowledge.rag.pipeline.loader.etl4lm import Etl4lmLoader


def test_request_kwargs_are_forwarded_and_override_defaults(tmp_path):
    file_path = tmp_path / "sample.pdf"
    file_path.write_bytes(b"sample")
    config = Etl4lmConf(
        url="http://etl4lm.example/predict",
        ocr_sdk_url="http://ocr.example",
        request_kwargs={"custom_option": "enabled", "force_ocr": False, "parameters": {"start": 2, "n": 3}},
    )
    loader = Etl4lmLoader(
        file_path=str(file_path),
        file_metadata={},
        file_extension="pdf",
        tmp_dir=str(tmp_path),
        **config.model_dump(),
    )
    response = Mock(status_code=200)
    response.json.return_value = {"status_code": 200, "partitions": [], "text": "parsed"}

    with patch("bisheng.knowledge.rag.pipeline.loader.etl4lm.requests.post", return_value=response) as post:
        documents = loader.load()

    payload = post.call_args.kwargs["json"]
    assert payload["custom_option"] == "enabled"
    assert payload["force_ocr"] is False
    assert payload["parameters"] == {"start": 2, "n": 3}
    assert payload["filename"] == "sample.pdf"
    assert payload["b64_data"] == ["c2FtcGxl"]
    assert documents[0].page_content == "parsed"


def test_request_kwargs_default_keeps_existing_payload(tmp_path):
    file_path = tmp_path / "sample.pdf"
    file_path.write_bytes(b"sample")
    loader = Etl4lmLoader(
        url="http://etl4lm.example/predict",
        ocr_sdk_url="http://ocr.example",
        file_path=str(file_path),
        file_metadata={},
        file_extension="pdf",
        tmp_dir=str(tmp_path),
    )
    response = Mock(status_code=200)
    response.json.return_value = {"status_code": 200, "partitions": [], "text": "parsed"}

    with patch("bisheng.knowledge.rag.pipeline.loader.etl4lm.requests.post", return_value=response) as post:
        loader.load()

    payload = post.call_args.kwargs["json"]
    assert payload["force_ocr"] is True
    assert payload["parameters"] == {"start": 0, "n": None, "filter_page_header_footer": False}
    assert Etl4lmConf().request_kwargs == {}
