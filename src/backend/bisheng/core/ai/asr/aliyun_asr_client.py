import asyncio
from typing import Any

from dashscope.audio.asr import Recognition, RecognitionResult

from ..base import ASRSegment, ASRTranscript, BaseASRClient, join_sentence_texts


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class AliyunASRClient(BaseASRClient):
    """Alibaba Cloud (DashScope) ASR client"""

    def __init__(self, api_key: str, model: str, **kwargs):
        self.api_key = api_key
        self.model = model
        self.recognition_kwargs = kwargs

    def _recognize(self, wav_path: str, model: str | None) -> RecognitionResult:
        # Recognition holds per-call streaming state, so build one per request.
        recognition = Recognition(
            model=model or self.model,
            format="wav",
            sample_rate=16000,
            callback=None,
            **self.recognition_kwargs,
        )
        return recognition.call(wav_path, api_key=self.api_key)

    async def transcribe_file(
        self,
        wav_path: str,
        language: str | None = None,
        model: str | None = None,
    ) -> ASRTranscript:
        # language is ignored: DashScope realtime models detect it themselves.
        result = await asyncio.to_thread(self._recognize, wav_path, model)
        if result.status_code != 200:
            raise RuntimeError(f"ASR request failed with status code {result.code} and message {result.message}")

        segments: list[ASRSegment] = []
        for sentence in result.get_sentence() or []:
            if not isinstance(sentence, dict):
                continue
            text = str(sentence.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                ASRSegment(
                    text=text,
                    begin_ms=_to_float(sentence.get("begin_time")),
                    end_ms=_to_float(sentence.get("end_time")),
                )
            )
        if segments:
            return ASRTranscript(text=join_sentence_texts([s.text for s in segments]), segments=segments)

        # No sentences recognized. Only fall back to an explicit plain-text field
        # on the output payload; never stringify the response object itself —
        # that would store the raw JSON envelope (status_code/request_id/...) as
        # the transcript and make silent media look successfully transcribed.
        output = getattr(result, "output", None)
        if isinstance(output, dict):
            fallback_text = str(output.get("text") or "").strip()
            if fallback_text:
                return ASRTranscript(text=fallback_text)
        return ASRTranscript(text="")
