import asyncio
import base64
import fnmatch
import ipaddress
import json
import os
import subprocess
import tempfile
import uuid
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

import dashscope
from dashscope.audio.asr import Recognition, RecognitionResult, Transcription

from ..base import ASRSegment, ASRTranscript, BaseASRClient, join_sentence_texts

# SDK wait() polls until the task ends and has no overall deadline. This bound
# only fails the caller; the in-flight DashScope task keeps running.
_TRANSCRIPTION_WAIT_SECONDS = 900

_PARAFORMER_FILE_MODELS = frozenset(
    {
        "paraformer-v1",
        "paraformer-v2",
        "paraformer-8k-v1",
        "paraformer-8k-v2",
        "paraformer-mtl-v1",
    }
)
_PARAFORMER_8K_MODELS = frozenset({"paraformer-8k-v1", "paraformer-8k-v2"})


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def asr_call_kind(model_name: str) -> str:
    """Pick the DashScope call for one file-ASR model id. Match is case-insensitive."""
    name = (model_name or "").strip().lower()
    if "qwen3-asr-flash" in name and "filetrans" in name:
        return "unsupported"
    if (
        "filetrans" in name
        or ("fun-asr" in name and "flash" not in name and "realtime" not in name)
        or name in _PARAFORMER_FILE_MODELS
    ):
        return "transcription"
    if "qwen3-asr-flash" in name and "realtime" not in name:
        return "qwen3"
    excluded = ("filetrans", "streaming", "message")
    if fnmatch.fnmatch(name, "qwen-audio-*-asr-flash") and not any(token in name for token in excluded):
        return "input_audio"
    if "fun-asr-flash" in name and "realtime" not in name:
        return "input_audio"
    return "recognition"


def _raise_if_http_error(result: Any) -> None:
    if getattr(result, "status_code", None) != 200:
        raise RuntimeError(f"ASR request failed with status code {result.code} and message {result.message}")


def _transcript_from_sentences(sentences: list[Any]) -> ASRTranscript:
    segments: list[ASRSegment] = []
    for sentence in sentences:
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
    if not segments:
        return ASRTranscript(text="")
    return ASRTranscript(text=join_sentence_texts([segment.text for segment in segments]), segments=segments)


def _choice_text(output: Any) -> str:
    message = output["choices"][0]["message"]
    content = message["content"] if isinstance(message, dict) else message.content
    item = content[0]
    if isinstance(item, dict):
        return str(item.get("text") or "").strip()
    return str(getattr(item, "text", "") or "").strip()


def _plain_output_text(output: Any) -> str:
    if not output:
        return ""
    try:
        value = output["text"]
    except (KeyError, TypeError):
        return ""
    return str(value or "").strip()


def dashscope_can_get(url: str) -> bool:
    """True when the URL is an HTTP(S) address DashScope's servers can fetch.

    Loopback and private addresses, including the internal MinIO share host, are refused.
    A DNS name is left to the operator: this process cannot know whether it is public.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.strip().lower()
    if host == "localhost":
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def resample_wav_8k(wav_path: str) -> str:
    """Return a new 8 kHz mono wav. The caller deletes it."""
    descriptor, output_path = tempfile.mkstemp(suffix="_8k_mono.wav")
    os.close(descriptor)
    command = ["ffmpeg", "-y", "-i", wav_path, "-ar", "8000", "-ac", "1", output_path]
    try:
        subprocess.run(command, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise RuntimeError("Failed to resample audio to 8 kHz for paraformer-8k") from exc
    return output_path


def publish_transcription_wav(wav_path: str) -> str:
    """Upload the wav and return a URL DashScope can GET.

    The share link keeps its host. A private or loopback host is an upload failure:
    DashScope cannot read the internal object store, and the call must not continue.
    """
    from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync

    storage = get_minio_storage_sync()
    object_name = f"asr-transcription/{uuid.uuid4().hex}.wav"
    bucket = storage.tmp_bucket
    storage.put_object_sync(
        bucket_name=bucket,
        object_name=object_name,
        file=wav_path,
        content_type="audio/wav",
    )
    url = storage.get_share_link_sync(object_name, bucket=bucket, clear_host=False)
    if not dashscope_can_get(url):
        raise RuntimeError(
            "Async transcription requires an audio URL that DashScope can GET. "
            "The object store share address is not publicly reachable, so the local wav was not submitted."
        )
    return url


def download_transcription_json(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError("transcription result URL is not HTTP")
    with urlopen(url, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("transcription result is not a JSON object")
    return payload


def _output_field(output: Any, key: str) -> Any:
    if isinstance(output, dict):
        return output[key]
    return output[key]


class AliyunASRClient(BaseASRClient):
    """Alibaba Cloud (DashScope) file ASR client."""

    def __init__(self, api_key: str, model: str, **kwargs):
        self.api_key = api_key
        self.model = model
        self.recognition_kwargs = kwargs

    def _model_name(self, model: str | None) -> str:
        return (model or self.model or "").strip()

    def _recognize(self, wav_path: str, model_name: str) -> RecognitionResult:
        # Recognition holds per-call streaming state, so build one per request.
        recognition = Recognition(
            model=model_name,
            format="wav",
            sample_rate=16000,
            callback=None,
            **self.recognition_kwargs,
        )
        return recognition.call(wav_path, api_key=self.api_key)

    def _transcript_from_recognition(self, result: RecognitionResult) -> ASRTranscript:
        _raise_if_http_error(result)
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
            return ASRTranscript(text=join_sentence_texts([segment.text for segment in segments]), segments=segments)

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

    def _call_qwen3(self, wav_path: str, model_name: str) -> ASRTranscript:
        # Local path is an upload field. Do not set dashscope.base_http_api_url.
        result = dashscope.MultiModalConversation.call(
            api_key=self.api_key,
            model=model_name,
            messages=[{"role": "user", "content": [{"audio": wav_path}]}],
            result_format="message",
            asr_options={"enable_itn": False},
        )
        _raise_if_http_error(result)
        output = getattr(result, "output", None)
        if not output:
            return ASRTranscript(text="")
        return ASRTranscript(text=_choice_text(output))

    def _call_input_audio(self, wav_path: str, model_name: str) -> ASRTranscript:
        # input_audio is not uploaded by the SDK, so the local path cannot be passed through.
        with open(wav_path, "rb") as audio_file:
            encoded = base64.b64encode(audio_file.read()).decode("ascii")
        data_uri = f"data:audio/wav;base64,{encoded}"
        result = dashscope.MultiModalConversation.call(
            api_key=self.api_key,
            model=model_name,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": data_uri},
                        }
                    ],
                }
            ],
            format="wav",
            sample_rate="16000",
        )
        _raise_if_http_error(result)
        return ASRTranscript(text=_plain_output_text(getattr(result, "output", None)))

    def _call_transcription(self, public_wav_url: str, model_name: str) -> ASRTranscript:
        result = Transcription.call(
            model=model_name,
            file_urls=[public_wav_url],
            api_key=self.api_key,
        )
        _raise_if_http_error(result)
        output = getattr(result, "output", None)
        if output is None:
            raise RuntimeError("Async transcription returned no output")
        task_status = _output_field(output, "task_status")
        if task_status != "SUCCEEDED":
            message = output.get("message") if isinstance(output, dict) else getattr(output, "message", None)
            raise RuntimeError(f"Async transcription failed: {message or task_status}")
        results = _output_field(output, "results") or []
        if not results:
            raise RuntimeError("Async transcription succeeded without results")
        item = results[0]
        if item.get("subtask_status") != "SUCCEEDED":
            raise RuntimeError(
                f"Async transcription subtask failed: {item.get('message') or item.get('subtask_status')}"
            )
        payload = download_transcription_json(item["transcription_url"])
        sentences: list[Any] = []
        for transcript in payload.get("transcripts") or []:
            if isinstance(transcript, dict):
                sentences.extend(transcript.get("sentences") or [])
        return _transcript_from_sentences(sentences)

    async def _transcribe_async_file(self, wav_path: str, model_name: str) -> ASRTranscript:
        upload_path = wav_path
        resampled = None
        try:
            if model_name.lower() in _PARAFORMER_8K_MODELS:
                resampled = await asyncio.to_thread(resample_wav_8k, wav_path)
                upload_path = resampled
            public_url = await asyncio.to_thread(publish_transcription_wav, upload_path)
        finally:
            if resampled and os.path.exists(resampled):
                os.remove(resampled)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._call_transcription, public_url, model_name),
                timeout=_TRANSCRIPTION_WAIT_SECONDS,
            )
        except TimeoutError as exc:
            raise RuntimeError("Async transcription timed out. The DashScope task was not cancelled.") from exc

    async def transcribe_file(
        self,
        wav_path: str,
        language: str | None = None,
        model: str | None = None,
    ) -> ASRTranscript:
        # language is ignored: these DashScope file models detect it themselves.
        model_name = self._model_name(model).lower()
        kind = asr_call_kind(model_name)
        if kind == "unsupported":
            raise RuntimeError(
                "qwen3-asr-flash-filetrans is not supported by DashScope SDK 1.25.0: "
                "the official request uses a single file_url and this SDK only submits file_urls"
            )
        if kind == "transcription":
            return await self._transcribe_async_file(wav_path, model_name)
        if kind == "qwen3":
            return await asyncio.to_thread(self._call_qwen3, wav_path, model_name)
        if kind == "input_audio":
            return await asyncio.to_thread(self._call_input_audio, wav_path, model_name)
        result = await asyncio.to_thread(self._recognize, wav_path, model_name)
        return self._transcript_from_recognition(result)
