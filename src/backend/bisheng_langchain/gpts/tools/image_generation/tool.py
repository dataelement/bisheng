"""One Images API implementation shared by configured and legacy image tools."""

import asyncio
import base64
import json
import logging
import re
import time
from collections.abc import Callable
from io import BytesIO
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from langchain_core.tools import BaseTool
from PIL import Image
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
IMAGE_TOOL_KEYS = frozenset({"image_generation", "dalle_image_generator"})
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024 * 1024


class ImageGenerationError(ValueError):
    """Safe failure text without upstream bodies or credentials."""


def normalize_image_config(value: dict, *, legacy: bool = True) -> dict[str, str]:
    if value.get("provider") not in (None, "", "openai") or value.get("azure_endpoint"):
        raise ImageGenerationError("Azure is not supported. Configure an OpenAI-compatible image service.")
    base = value.get("openai_api_base", "https://api.openai.com/v1")
    model = value.get("model", "dall-e-3" if legacy else "")
    key = value.get("openai_api_key", "")
    if not all(isinstance(item, str) and item.strip() for item in (base, model, key)):
        raise ImageGenerationError("API address, API key and model are required.")
    if len(model) > 200 or any(ord(c) < 32 for c in model + key):
        raise ImageGenerationError("Invalid image generation configuration.")
    if not key.strip("*"):
        raise ImageGenerationError("Enter a valid API key.")
    try:
        parsed = urlsplit(base.strip())
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or any(c.isspace() for c in base.strip())
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.port == 0
        ):
            raise ValueError
        path = re.sub(r"/images/generations/?$", "", parsed.path.rstrip("/"))
        base = urlunsplit((parsed.scheme, parsed.netloc, path.rstrip("/"), "", ""))
    except ValueError:
        raise ImageGenerationError(
            "Enter a valid HTTP(S) API base URL without credentials or query parameters."
        ) from None
    proxy = value.get("openai_proxy") or ""
    if not isinstance(proxy, str):
        raise ImageGenerationError("Invalid image proxy.")
    return {
        "openai_api_base": base,
        "openai_api_key": key.strip(),
        "model": model.strip(),
        "openai_proxy": proxy.strip(),
    }


class ImageInput(BaseModel):
    query: str = Field(min_length=1, max_length=8000, description="Description of the image to generate.")


class ImageGenerationTool(BaseTool):
    name: str = "image_generation"
    description: str = (
        "Generate images from a text description using the configured image service and model. Returns image links."
    )
    args_schema: type[BaseModel] = ImageInput
    image_config: dict[str, str] = Field(exclude=True, repr=False)
    upload_image: Callable[[bytes, str], str] | None = Field(default=None, exclude=True, repr=False)

    def _read_response(self, response: httpx.Response, started: float) -> bytes:
        limit = MAX_RESPONSE_BYTES if response.is_success else 64 * 1024
        data = bytearray()
        for chunk in response.iter_bytes():
            if time.monotonic() - started > 180:
                raise ImageGenerationError("Image service request timed out.")
            if len(data) + len(chunk) > limit:
                if not response.is_success:
                    break  # Error bodies are optional; preserve the HTTP status.
                raise ImageGenerationError("Image service response exceeds the size limit.")
            data.extend(chunk)
        if not response.is_success:
            details = [f"HTTP {response.status_code}"]
            try:
                payload = json.loads(data)
                code = payload.get("error", {}).get("code")
            except (ValueError, AttributeError):
                code = None
            for label, value in (
                ("code", code),
                ("request_id", response.headers.get("x-request-id") or response.headers.get("x-tt-logid")),
            ):
                if (
                    isinstance(value, str)
                    and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value)
                    and self.image_config["openai_api_key"] not in value
                ):
                    details.append(f"{label}={value}")
            raise ImageGenerationError(f"Image service rejected the request ({'; '.join(details)}).")
        return bytes(data)

    def _results(self, raw: bytes) -> str:
        try:
            items = json.loads(raw)["data"]
            if not isinstance(items, list) or not items:
                raise ValueError
            images = []
            for item in items:
                url = item.get("url")
                if url:
                    parsed = urlsplit(url)
                    if (
                        parsed.scheme not in ("http", "https")
                        or not parsed.hostname
                        or parsed.username
                        or parsed.password
                        or any(c.isspace() for c in url)
                        or self.image_config["openai_api_key"] in url
                    ):
                        raise ValueError
                    images.append(quote(url, safe=":/?&=%#+@!$;,~*'[]"))
                    continue
                encoded = item["b64_json"]
                if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
                    raise ValueError
                data = base64.b64decode(encoded, validate=True)
                if not data or len(data) > MAX_IMAGE_BYTES:
                    raise ValueError
                with Image.open(BytesIO(data)) as image:
                    mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(image.format)
                    if mime is None:
                        raise ValueError
                    image.verify()
                images.append((data, mime))
        except (ValueError, TypeError, KeyError, AttributeError, OSError, Image.DecompressionBombError):
            logger.warning("Image service returned an invalid image response")
            raise ImageGenerationError("Image service returned no valid images.") from None
        links = []
        for image in images:
            if isinstance(image, tuple):
                if self.upload_image is None:
                    raise ImageGenerationError("Image storage is unavailable.")
                try:
                    image = self.upload_image(*image)
                except Exception as error:
                    logger.warning("Image storage failed (%s)", type(error).__name__)
                    raise ImageGenerationError("Image storage failed.") from None
            links.append(f"![image {len(links) + 1}]({image})")
        return "\n".join(links)

    def _run(self, query: str, **kwargs) -> str:
        if not isinstance(query, str) or not query.strip() or len(query) > 8000:
            raise ImageGenerationError("Enter an image description of up to 8000 characters.")
        conf = self.image_config
        try:
            started = time.monotonic()
            with httpx.Client(
                timeout=httpx.Timeout(180, connect=10), proxy=conf["openai_proxy"] or None, trust_env=False
            ) as client:
                with client.stream(
                    "POST",
                    conf["openai_api_base"] + "/images/generations",
                    headers={"Authorization": f"Bearer {conf['openai_api_key']}"},
                    json={"model": conf["model"], "prompt": query},
                ) as response:
                    raw = self._read_response(response, started)
        except httpx.TimeoutException:
            logger.warning("Image service timed out")
            raise ImageGenerationError("Image service request timed out.") from None
        except (httpx.HTTPError, ValueError) as error:
            if isinstance(error, ImageGenerationError):
                raise
            logger.warning("Image service request failed (%s)", type(error).__name__)
            raise ImageGenerationError("Image service request failed.") from None
        return self._results(raw)

    async def _arun(self, query: str, **kwargs) -> str:
        return await asyncio.to_thread(self._run, query)


def build_image_generation_tool(*, name: str = "image_generation", upload_image=None, **config) -> ImageGenerationTool:
    return ImageGenerationTool(name=name, image_config=normalize_image_config(config), upload_image=upload_image)
