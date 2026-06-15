import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any

from dashscope.audio.asr import Recognition, RecognitionResult
from loguru import logger

from bisheng.common.errcode.knowledge import KnowledgeMediaTranscriptionError
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
    begin_time: int | None = None
    end_time: int | None = None


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
        wav_path = cls._convert_to_wav(media_path)
        try:
            segments = cls._call_aliyun_asr(
                wav_path,
                api_key=api_key,
                model_name=model_info.model_name,
            )
        finally:
            if os.path.exists(wav_path):
                os.remove(wav_path)

        text = "\n".join(segment.text for segment in segments if segment.text).strip()
        if not text:
            raise KnowledgeMediaTranscriptionError(msg="ASR returned empty text")

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
            raise KnowledgeMediaTranscriptionError(msg="Media audio extraction failed") from exc
        return wav_path

    @classmethod
    def _call_aliyun_asr(cls, wav_path: str, *, api_key: str, model_name: str) -> list[TranscriptSegment]:
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
                    begin_time=cls._coerce_time_ms(sentence.get("begin_time")),
                    end_time=cls._coerce_time_ms(sentence.get("end_time")),
                )
            )
        if segments:
            return segments

        text = str(getattr(result, "output", {}) or result).strip()
        return [TranscriptSegment(text=text)] if text else []

    @staticmethod
    def _coerce_time_ms(value: Any) -> int | None:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number <= 0:
            return 0
        if number < 10_000:
            return int(number * 1000)
        return int(number)

    @classmethod
    def _build_markdown(
        cls,
        *,
        source_file_name: str,
        model_name: str,
        segments: list[TranscriptSegment],
    ) -> str:
        lines = [
            f"# {source_file_name} 转写文本",
            "",
            f"- 来源文件: {source_file_name}",
            f"- ASR 模型: {model_name}",
            "",
            "## 转写内容",
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
