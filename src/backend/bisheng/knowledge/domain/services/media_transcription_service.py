import glob
import os
import pickle
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from typing import Any

from loguru import logger
from redis.exceptions import RedisError

from bisheng.common.errcode.knowledge import (
    KnowledgeMediaNoRecognizableAudioError,
    KnowledgeMediaTranscriptionError,
)
from bisheng.common.errcode.server import (
    AsrModelConfigDeletedError,
    AsrModelOfflineError,
    AsrModelTypeError,
    AsrProviderDeletedError,
    NoAsrModelConfigError,
)
from bisheng.core.ai.base import ASRTranscript
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.llm.asr import BishengASR, is_asr_provider_supported
from bisheng.llm.domain.models import LLMDao, LLMModel, LLMServer
from bisheng.llm.domain.services.llm import LLMService
from bisheng.utils.util import calculate_md5
from bisheng.utils.async_utils import run_async_safe

# Standard /audio/transcriptions takes the whole file in one request (OpenAI caps
# it at 25 MB, gateways often lower). 5 minutes of 16k mono wav is ~9.6 MB.
CHUNK_SECONDS = 300

# Knowledge-base preview and ingest each run the whole pipeline, and every split
# rule tweak in preview reruns it, so one upload used to hit the ASR model
# several times. Keep the result as long as the preview chunk cache lives.
TRANSCRIPT_CACHE_TTL_SECONDS = 86400
TRANSCRIPT_CACHE_ERRORS = (RedisError, OSError, ValueError, TypeError, KeyError, pickle.UnpicklingError)


@dataclass
class TranscriptSegment:
    text: str
    begin_time: float | None = None
    end_time: float | None = None


@dataclass
class TranscriptResult:
    text: str
    markdown: str
    segments: list[TranscriptSegment]
    model_id: int
    model_name: str


@dataclass
class AudioChunk:
    path: str
    offset_ms: int
    duration_ms: int | None


class KnowledgeMediaTranscriptionService:
    """Audio/video file transcription shared by knowledge base, knowledge space
    and daily-mode attachments (every BaseFilePipeline media loader).

    Provider calls go through the same ASR clients as workbench voice input;
    this service owns the file-level flow: convert, chunk, transcribe, stitch.
    """

    @classmethod
    def transcribe_media(
        cls,
        media_path: str,
        *,
        source_file_name: str,
        tenant_id: int | None = None,
    ) -> TranscriptResult:
        if not os.path.exists(media_path):
            raise KnowledgeMediaTranscriptionError(msg="Media file does not exist")

        model_info, server_info = cls._resolve_asr_model(tenant_id)
        cls._resolve_api_key(server_info, model_info)

        cache_key = cls._transcript_cache_key(media_path, tenant_id, model_info, server_info)
        cached = cls._load_cached_transcript(cache_key)
        if cached is not None:
            logger.info(
                "knowledge media transcript cache hit file={} model={}", source_file_name, model_info.model_name
            )
            return cached

        duration_ms = cls._probe_media_duration_ms(media_path)
        wav_path = cls._convert_to_wav(media_path)
        chunk_dir = tempfile.mkdtemp(prefix="asr_chunks_")
        try:
            chunks = cls._split_wav(wav_path, chunk_dir, media_duration_ms=duration_ms)
            segments = cls._transcribe_chunks(model_info, server_info, chunks)
        finally:
            if os.path.exists(wav_path):
                os.remove(wav_path)
            shutil.rmtree(chunk_dir, ignore_errors=True)

        text = "\n".join(segment.text for segment in segments if segment.text).strip()
        if not text:
            raise KnowledgeMediaNoRecognizableAudioError()

        markdown = cls._build_markdown(
            source_file_name=source_file_name,
            model_name=model_info.model_name,
            segments=segments,
        )
        result = TranscriptResult(
            text=text,
            markdown=markdown,
            segments=segments,
            model_id=model_info.id,
            model_name=model_info.model_name,
        )
        cls._save_cached_transcript(cache_key, result)
        return result

    @staticmethod
    def _transcript_cache_key(
        media_path: str,
        tenant_id: int | None,
        model_info: LLMModel,
        server_info: LLMServer,
    ) -> str:
        # Any edit to the model or its provider (endpoint, key, model name) bumps
        # update_time, so a changed configuration never reuses an old transcript.
        tenant = tenant_id if tenant_id is not None else get_current_tenant_id()
        model_version = getattr(model_info.update_time, "isoformat", lambda: "")()
        server_version = getattr(server_info.update_time, "isoformat", lambda: "")()
        return (
            f"knowledge_media_transcript:{tenant or 0}:{model_info.id}:{model_version}:{server_version}:"
            f"{calculate_md5(media_path)}"
        )

    @staticmethod
    def _load_cached_transcript(cache_key: str) -> TranscriptResult | None:
        try:
            cached = get_redis_client_sync().get(cache_key)
            if not cached:
                return None
            return TranscriptResult(
                text=cached["text"],
                markdown=cached["markdown"],
                segments=[TranscriptSegment(**segment) for segment in cached["segments"]],
                model_id=cached["model_id"],
                model_name=cached["model_name"],
            )
        except TRANSCRIPT_CACHE_ERRORS:
            # Best-effort: a cache failure only costs a fresh transcription.
            logger.opt(exception=True).warning("knowledge media transcript cache read failed key={}", cache_key)
            return None

    @staticmethod
    def _save_cached_transcript(cache_key: str, result: TranscriptResult) -> None:
        # Stored as plain dicts rather than pickled dataclasses so a renamed or
        # moved class never turns cached entries into unreadable blobs.
        payload = asdict(result)
        try:
            get_redis_client_sync().set(cache_key, payload, expiration=TRANSCRIPT_CACHE_TTL_SECONDS)
        except TRANSCRIPT_CACHE_ERRORS:
            # Best-effort: the transcript is already produced; next run just re-transcribes.
            logger.opt(exception=True).warning("knowledge media transcript cache write failed key={}", cache_key)

    @classmethod
    def _resolve_asr_model(cls, tenant_id: int | None) -> tuple[LLMModel, LLMServer]:
        knowledge_llm = LLMService.get_knowledge_llm(tenant_id=tenant_id)
        if not knowledge_llm.asr_model_id:
            raise NoAsrModelConfigError()

        model_info = LLMDao.get_model_by_id(int(knowledge_llm.asr_model_id))
        if not model_info:
            raise AsrModelConfigDeletedError()
        if model_info.model_type != LLMModelType.ASR.value:
            raise AsrModelTypeError(model_type=model_info.model_type)

        server_info = LLMDao.get_server_by_id(model_info.server_id)
        if not server_info:
            raise AsrProviderDeletedError()
        if not model_info.online:
            raise AsrModelOfflineError(server_name=server_info.name, model_name=model_info.model_name)
        if not is_asr_provider_supported(server_info.type):
            raise KnowledgeMediaTranscriptionError(
                msg=f"Knowledge media transcription does not support ASR provider {server_info.type}"
            )
        return model_info, server_info

    @classmethod
    def _resolve_api_key(cls, server_info: LLMServer, model_info: LLMModel) -> str:
        params: dict[str, Any] = {}
        if server_info.config:
            params.update(server_info.config)
        if model_info.config:
            params.update(model_info.config)
        api_key = params.get("openai_api_key") or params.get("api_key")
        if not api_key:
            raise KnowledgeMediaTranscriptionError(msg="ASR api key is missing")
        return api_key

    @classmethod
    def _convert_to_wav(cls, media_path: str) -> str:
        fd, wav_path = tempfile.mkstemp(suffix="_16k_mono.wav")
        os.close(fd)
        command = [
            "ffmpeg",
            "-y",
            "-i",
            media_path,
            "-ar",
            "16000",
            "-ac",
            "1",
            wav_path,
        ]
        try:
            subprocess.run(command, capture_output=True, check=True)
        except FileNotFoundError as exc:
            raise KnowledgeMediaTranscriptionError(msg="ffmpeg is not installed") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else ""
            logger.warning("ffmpeg media conversion failed: {}", stderr[-1000:])
            if cls._is_missing_audio_stream_error(stderr):
                raise KnowledgeMediaNoRecognizableAudioError() from exc
            raise KnowledgeMediaTranscriptionError(msg="Media audio extraction failed") from exc
        return wav_path

    @staticmethod
    def _is_missing_audio_stream_error(stderr: str) -> bool:
        normalized = stderr.lower()
        return any(
            marker in normalized
            for marker in (
                "does not contain any stream",
                "matches no streams",
                "stream specifier ':a'",
                "audio: none",
            )
        )

    @classmethod
    def _split_wav(cls, wav_path: str, chunk_dir: str, *, media_duration_ms: int | None) -> list[AudioChunk]:
        """Cut the wav into CHUNK_SECONDS pieces; short media stays one chunk."""
        if media_duration_ms is not None and media_duration_ms <= CHUNK_SECONDS * 1000:
            return [AudioChunk(path=wav_path, offset_ms=0, duration_ms=media_duration_ms)]

        command = [
            "ffmpeg",
            "-y",
            "-i",
            wav_path,
            "-f",
            "segment",
            "-segment_time",
            str(CHUNK_SECONDS),
            "-c",
            "copy",
            os.path.join(chunk_dir, "chunk_%05d.wav"),
        ]
        try:
            subprocess.run(command, capture_output=True, check=True)
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else ""
            logger.warning("ffmpeg audio chunking failed: {}", stderr[-1000:])
            raise KnowledgeMediaTranscriptionError(msg="Media audio extraction failed") from exc

        chunk_paths = sorted(glob.glob(os.path.join(chunk_dir, "chunk_*.wav")))
        if not chunk_paths:
            raise KnowledgeMediaTranscriptionError(msg="Media audio extraction failed")

        chunks: list[AudioChunk] = []
        offset_ms = 0
        for path in chunk_paths:
            duration_ms = cls._probe_media_duration_ms(path)
            chunks.append(AudioChunk(path=path, offset_ms=offset_ms, duration_ms=duration_ms))
            # Offsets come from measured chunk lengths; the nominal length is only a
            # fallback when ffprobe is unavailable.
            offset_ms += duration_ms if duration_ms is not None else CHUNK_SECONDS * 1000
        return chunks

    @classmethod
    def _transcribe_chunks(
        cls,
        model_info: LLMModel,
        server_info: LLMServer,
        chunks: list[AudioChunk],
    ) -> list[TranscriptSegment]:
        # Loaders run synchronously (Celery threads, asyncio.to_thread); the ASR
        # clients are async. A long recording legitimately takes many minutes.
        return run_async_safe(cls._atranscribe_chunks(model_info, server_info, chunks), timeout=None)

    @classmethod
    async def _atranscribe_chunks(
        cls,
        model_info: LLMModel,
        server_info: LLMServer,
        chunks: list[AudioChunk],
    ) -> list[TranscriptSegment]:
        client = await BishengASR.init_asr_client(model_info=model_info, server_info=server_info)
        segments: list[TranscriptSegment] = []
        try:
            for index, chunk in enumerate(chunks):
                try:
                    transcript = await client.transcribe_file(chunk.path)
                except Exception as exc:
                    logger.exception(
                        "knowledge media ASR failed on chunk {}/{} model={}",
                        index + 1,
                        len(chunks),
                        model_info.model_name,
                    )
                    message = str(exc)
                    if not message.lower().startswith("asr request failed"):
                        message = f"ASR request failed: {message}"
                    raise KnowledgeMediaTranscriptionError(msg=message) from exc

                chunk_segments = cls._normalize_segments(
                    cls._segments_from_transcript(transcript),
                    media_duration_ms=chunk.duration_ms,
                )
                for segment in chunk_segments:
                    if segment.begin_time is not None:
                        segment.begin_time += chunk.offset_ms
                    if segment.end_time is not None:
                        segment.end_time += chunk.offset_ms
                segments.extend(chunk_segments)
        finally:
            await client.aclose()
        return segments

    @classmethod
    def _segments_from_transcript(cls, transcript: ASRTranscript) -> list[TranscriptSegment]:
        segments = [
            TranscriptSegment(
                text=segment.text,
                begin_time=cls._coerce_time_value(segment.begin_ms),
                end_time=cls._coerce_time_value(segment.end_ms),
            )
            for segment in transcript.segments
            if segment.text.strip()
        ]
        if segments:
            return segments
        # Provider returned plain text only: keep it, without a timeline.
        text = transcript.text.strip()
        return [TranscriptSegment(text=text)] if text else []

    @staticmethod
    def _coerce_time_value(value: Any) -> float | None:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number <= 0:
            return 0
        return number

    @classmethod
    def _normalize_segments(
        cls,
        segments: list[TranscriptSegment],
        *,
        media_duration_ms: int | None = None,
    ) -> list[TranscriptSegment]:
        raw_times = [
            time_value
            for segment in segments
            for time_value in (segment.begin_time, segment.end_time)
            if time_value is not None
        ]
        multiplier = cls._resolve_timestamp_multiplier(
            raw_times,
            media_duration_ms=media_duration_ms,
        )

        normalized_segments: list[tuple[int, TranscriptSegment]] = []
        for index, segment in enumerate(segments):
            begin_time = cls._scale_timestamp(segment.begin_time, multiplier)
            end_time = cls._scale_timestamp(segment.end_time, multiplier)
            if begin_time is not None and end_time is not None and end_time < begin_time:
                logger.warning(
                    "ASR segment end_time precedes begin_time; clamping end_time. begin_time={} end_time={} text={}",
                    begin_time,
                    end_time,
                    segment.text[:80],
                )
                end_time = begin_time
            normalized_segments.append(
                (
                    index,
                    TranscriptSegment(
                        text=segment.text,
                        begin_time=begin_time,
                        end_time=end_time,
                    ),
                )
            )

        normalized_segments.sort(
            key=lambda item: (
                item[1].begin_time is None,
                item[1].begin_time if item[1].begin_time is not None else 0,
                item[0],
            )
        )
        return [segment for _, segment in normalized_segments]

    @staticmethod
    def _resolve_timestamp_multiplier(
        raw_times: list[float],
        *,
        media_duration_ms: int | None = None,
    ) -> int:
        positive_times = [time_value for time_value in raw_times if time_value > 0]
        if not positive_times:
            return 1

        max_time = max(positive_times)
        if media_duration_ms and media_duration_ms > 0:
            tolerance_ms = max(5000, int(media_duration_ms * 0.2))
            candidates = (1, 10, 1000)
            valid_candidates = []
            for multiplier in candidates:
                scaled_max = max_time * multiplier
                overflow = max(0, scaled_max - media_duration_ms - tolerance_ms)
                distance = abs(media_duration_ms - scaled_max)
                valid_candidates.append((overflow, distance, multiplier))
            valid_candidates.sort()
            return valid_candidates[0][2]

        if max_time >= 1000:
            return 1
        return 1000

    @staticmethod
    def _scale_timestamp(value: float | None, multiplier: int) -> int | None:
        if value is None:
            return None
        return max(0, int(round(value * multiplier)))

    @staticmethod
    def _probe_media_duration_ms(media_path: str) -> int | None:
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            media_path,
        ]
        try:
            result = subprocess.run(command, capture_output=True, check=True)
        except FileNotFoundError:
            logger.warning("ffprobe is not installed; ASR timestamp normalization will not use media duration")
            return None
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else ""
            logger.warning("ffprobe media duration probe failed: {}", stderr[-1000:])
            return None

        duration_text = result.stdout.decode("utf-8", errors="ignore").strip()
        try:
            duration_seconds = float(duration_text)
        except ValueError:
            logger.warning("ffprobe returned invalid media duration: {}", duration_text[:120])
            return None
        if duration_seconds <= 0:
            return None
        return int(duration_seconds * 1000)

    @classmethod
    def _build_markdown(
        cls,
        *,
        source_file_name: str,
        model_name: str,
        segments: list[TranscriptSegment],
    ) -> str:
        entry_text = "\n".join(segment.text for segment in segments if segment.text).strip()
        lines = [
            "## 入库文本",
            "",
            entry_text,
            "",
            "## 识别文本",
            "",
        ]
        for segment in segments:
            if segment.begin_time is not None or segment.end_time is not None:
                begin = cls._format_timestamp(segment.begin_time)
                end = cls._format_timestamp(segment.end_time)
                lines.append(f"[{begin} - {end}] {segment.text}")
            else:
                lines.append(segment.text)
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _format_timestamp(milliseconds: int | None) -> str:
        if milliseconds is None:
            return "--:--:--"
        seconds = max(0, int(milliseconds / 1000))
        h, rest = divmod(seconds, 3600)
        m, s = divmod(rest, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
