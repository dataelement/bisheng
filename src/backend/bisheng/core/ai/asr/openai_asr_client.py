from typing import Any

import openai
from loguru import logger

from ..base import ASRSegment, ASRTranscript, BaseASRClient, join_sentence_texts


def _read_field(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _seconds_to_ms(value: Any) -> float | None:
    try:
        return float(value) * 1000
    except (TypeError, ValueError):
        return None


async def transcribe_with_openai_sdk(
    client: openai.AsyncOpenAI,
    wav_path: str,
    *,
    model: str,
    language: str | None = None,
) -> ASRTranscript:
    """Call the standard /audio/transcriptions endpoint (OpenAI and compatible servers).

    Asks for ``verbose_json`` to get segment timestamps. Servers or models that
    reject it (e.g. gpt-4o-transcribe, many self-hosted wrappers) get a second,
    plain request, and the transcript then carries text only.
    """
    params: dict[str, Any] = {"model": model}
    if language and language != "auto":
        params["language"] = language

    try:
        with open(wav_path, "rb") as f:
            response = await client.audio.transcriptions.create(file=f, response_format="verbose_json", **params)
    except (openai.BadRequestError, openai.UnprocessableEntityError) as exc:
        logger.warning("ASR model {} rejected verbose_json, retrying without timestamps: {}", model, exc)
        with open(wav_path, "rb") as f:
            response = await client.audio.transcriptions.create(file=f, **params)

    segments: list[ASRSegment] = []
    for item in _read_field(response, "segments") or []:
        text = str(_read_field(item, "text") or "").strip()
        if not text:
            continue
        segments.append(
            ASRSegment(
                text=text,
                begin_ms=_seconds_to_ms(_read_field(item, "start")),
                end_ms=_seconds_to_ms(_read_field(item, "end")),
            )
        )
    text = str(_read_field(response, "text") or "").strip()
    if not text and segments:
        text = join_sentence_texts([segment.text for segment in segments])
    return ASRTranscript(text=text, segments=segments)


class OpenAIASRClient(BaseASRClient):
    """OpenAI ASR client; also serves any OpenAI-compatible endpoint via base_url."""

    def __init__(self, api_key: str, **kwargs):
        self.model = kwargs.pop("model", "whisper-1")
        self.client = openai.AsyncOpenAI(api_key=api_key, **kwargs)

    async def transcribe_file(
        self,
        wav_path: str,
        language: str | None = None,
        model: str | None = None,
    ) -> ASRTranscript:
        return await transcribe_with_openai_sdk(
            self.client,
            wav_path,
            model=model or self.model,
            language=language,
        )

    async def aclose(self) -> None:
        await self.client.close()
