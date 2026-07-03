import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any

from dashscope.audio.asr import Recognition, RecognitionResult
from loguru import logger

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
from bisheng.llm.domain.const import LLMModelType, LLMServerType
from bisheng.llm.domain.models import LLMDao, LLMModel, LLMServer
from bisheng.llm.domain.services.llm import LLMService


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


class KnowledgeMediaTranscriptionService:
    """Knowledge-base specific media transcription service.

    This service intentionally does not use the existing BaseASRClient path
    because that path preserves legacy workbench behavior.
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
        api_key = cls._resolve_api_key(server_info, model_info)
        duration_ms = cls._probe_media_duration_ms(media_path)
        wav_path = cls._convert_to_wav(media_path)
        try:
            segments = cls._call_aliyun_asr(
                wav_path,
                api_key=api_key,
                model_name=model_info.model_name,
                media_duration_ms=duration_ms,
            )
        finally:
            if os.path.exists(wav_path):
                os.remove(wav_path)

        text = "\n".join(segment.text for segment in segments if segment.text).strip()
        if not text:
            raise KnowledgeMediaNoRecognizableAudioError()

        markdown = cls._build_markdown(
            source_file_name=source_file_name,
            model_name=model_info.model_name,
            segments=segments,
        )
        return TranscriptResult(
            text=text,
            markdown=markdown,
            segments=segments,
            model_id=model_info.id,
            model_name=model_info.model_name,
        )

    @classmethod
    def _resolve_asr_model(cls, tenant_id: int | None) -> tuple[LLMModel, LLMServer]:
        workbench_llm = LLMService.get_workbench_llm_sync(tenant_id=tenant_id)
        if not workbench_llm.asr_model or not workbench_llm.asr_model.id:
            raise NoAsrModelConfigError()

        model_info = LLMDao.get_model_by_id(int(workbench_llm.asr_model.id))
        if not model_info:
            raise AsrModelConfigDeletedError()
        if model_info.model_type != LLMModelType.ASR.value:
            raise AsrModelTypeError(model_type=model_info.model_type)

        server_info = LLMDao.get_server_by_id(model_info.server_id)
        if not server_info:
            raise AsrProviderDeletedError()
        if not model_info.online:
            raise AsrModelOfflineError(server_name=server_info.name, model_name=model_info.model_name)
        if server_info.type != LLMServerType.QWEN.value:
            raise KnowledgeMediaTranscriptionError(
                msg=f"Knowledge media transcription only supports Aliyun/Qwen ASR, got {server_info.type}"
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
    def _call_aliyun_asr(
        cls,
        wav_path: str,
        *,
        api_key: str,
        model_name: str,
        media_duration_ms: int | None = None,
    ) -> list[TranscriptSegment]:
        recognition = Recognition(
            model=model_name,
            format="wav",
            sample_rate=16000,
            callback=None,
        )
        result: RecognitionResult = recognition.call(wav_path, api_key=api_key)
        if result.status_code != 200:
            raise KnowledgeMediaTranscriptionError(
                msg=f"ASR request failed: {result.code} {result.message}"
            )

        raw_sentences = result.get_sentence() or []
        segments: list[TranscriptSegment] = []
        for sentence in raw_sentences:
            if not isinstance(sentence, dict):
                continue
            text = str(sentence.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    text=text,
                    begin_time=cls._coerce_time_value(sentence.get("begin_time")),
                    end_time=cls._coerce_time_value(sentence.get("end_time")),
                )
            )
        if segments:
            return cls._normalize_segments(segments, media_duration_ms=media_duration_ms)

        text = str(getattr(result, "output", {}) or result).strip()
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
                    "ASR segment end_time precedes begin_time; clamping end_time. "
                    "begin_time={} end_time={} text={}",
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
            logger.warning(
                "ffprobe is not installed; ASR timestamp normalization will not use media duration"
            )
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
