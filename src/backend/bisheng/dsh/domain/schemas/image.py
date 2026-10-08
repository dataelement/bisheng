"""Bounded inline image input; external URLs are kept outside the proxy contract."""

import base64
import binascii
from typing import Annotated, Literal

from pydantic import Field, model_validator

from bisheng.dsh.domain.schemas.contracts import DshContract


class ImageUrl(DshContract):
    url: str = Field(max_length=7_000_000)
    detail: Literal["auto", "low", "high"] = "auto"

    @model_validator(mode="after")
    def inline_image(self):
        prefix, separator, encoded = self.url.partition(",")
        signatures = {
            "data:image/png;base64": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
            "data:image/jpeg;base64": lambda data: data.startswith(b"\xff\xd8\xff"),
            "data:image/gif;base64": lambda data: data[:6] in (b"GIF87a", b"GIF89a"),
            "data:image/webp;base64": lambda data: data[:4] == b"RIFF" and data[8:12] == b"WEBP",
        }
        if not separator or prefix not in signatures:
            raise ValueError("Use an inline PNG, JPEG, GIF or WebP image")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Invalid image encoding") from None
        if len(data) > 5 * 1024 * 1024 or not signatures[prefix](data):
            raise ValueError("Image must match its format and be at most 5 MiB")
        return self


class ImagePart(DshContract):
    type: Literal["image_url"]
    image_url: ImageUrl


class TextPart(DshContract):
    type: Literal["text"]
    text: str


ContentPart = Annotated[TextPart | ImagePart, Field(discriminator="type")]
