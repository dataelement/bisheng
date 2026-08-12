from typing import Any


def build_image_generation_payload(
    *,
    prompt: str,
    model: str,
    aspect_ratio: str | None,
    width: int | None,
    height: int | None,
    response_format: str,
    seed: int | None,
    n: int,
    prompt_optimizer: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "response_format": response_format,
        "n": n,
        "prompt_optimizer": prompt_optimizer,
    }
    optional_fields = {
        "aspect_ratio": aspect_ratio,
        "width": width,
        "height": height,
        "seed": seed,
    }
    payload.update({key: value for key, value in optional_fields.items() if value is not None})
    return payload


def parse_image_generation_response(payload: dict[str, Any], response_format: str) -> dict[str, Any]:
    base_response = payload.get("base_resp")
    if not isinstance(base_response, dict) or base_response.get("status_code") != 0:
        message = base_response.get("status_msg") if isinstance(base_response, dict) else None
        raise ValueError(message or "MiniMax image generation failed")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("MiniMax image generation returned no image data")
    response_key = "image_urls" if response_format == "url" else "image_base64"
    images = data.get(response_key)
    if not isinstance(images, list) or not images or not all(isinstance(image, str) for image in images):
        raise ValueError("MiniMax image generation returned invalid image data")

    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        "response_format": response_format,
        "images": images,
        "success_count": metadata.get("success_count", len(images)),
        "failed_count": metadata.get("failed_count", 0),
    }
