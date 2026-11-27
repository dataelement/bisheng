import io
import json
import zipfile

import pytest
from PIL import Image

from bisheng.finetune.domain.services.finetune_file import FinetuneFileService


def _image_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(stream, format="PNG")
    return stream.getvalue()


def test_text_records_accept_alpaca():
    FinetuneFileService.validate_text_records(
        [
            {"instruction": "classify", "input": "ticket", "output": "OPS"},
        ]
    )


def test_image_text_zip_is_validated():
    stream = io.BytesIO()
    records = [
        {
            "messages": [{"role": "user", "content": "<image>describe"}, {"role": "assistant", "content": "receipt"}],
            "images": ["media/sample.png"],
        }
    ]
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("train.json", json.dumps(records))
        archive.writestr("media/sample.png", _image_bytes())
    assert FinetuneFileService.validate_image_text_archive(stream.getvalue()) == (1, 1)


def test_image_text_zip_rejects_traversal():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../escape", "bad")
    with pytest.raises(ValueError, match="Unsafe ZIP member"):
        FinetuneFileService.validate_image_text_archive(stream.getvalue())
