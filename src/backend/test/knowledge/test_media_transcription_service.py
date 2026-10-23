import asyncio
import subprocess
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from bisheng.common.errcode.knowledge import KnowledgeMediaNoRecognizableAudioError, KnowledgeMediaTranscriptionError
from bisheng.common.errcode.server import NoAsrModelConfigError
from bisheng.core.ai.base import ASRSegment, ASRTranscript
from bisheng.knowledge.domain.services.media_transcription_service import (
    CHUNK_SECONDS,
    AudioChunk,
    KnowledgeMediaTranscriptionService,
    TranscriptSegment,
)
from bisheng.llm.domain.const import LLMModelType, LLMServerType
from bisheng.llm.domain.schemas import KnowledgeLLMConfig


def test_normalize_segments_keeps_aliyun_millisecond_timestamps_consistent() -> None:
    segments = [
        TranscriptSegment("Again after seeing.", begin_time=3760, end_time=5160),
        TranscriptSegment(
            "My entire life's been spent only in one industry.",
            begin_time=6660,
            end_time=10000,
        ),
        TranscriptSegment(
            "But I've been in it now for about 15 years.",
            begin_time=10000,
            end_time=22000,
        ),
    ]

    normalized = KnowledgeMediaTranscriptionService._normalize_segments(
        segments,
        media_duration_ms=30_000,
    )

    assert [(item.begin_time, item.end_time) for item in normalized] == [
        (3760, 5160),
        (6660, 10000),
        (10000, 22000),
    ]
    markdown = KnowledgeMediaTranscriptionService._build_markdown(
        source_file_name="jobs.m4a",
        model_name="paraformer-realtime-v2",
        segments=normalized,
    )
    assert "[00:00:06 - 00:00:10] My entire life's been spent only in one industry." in markdown
    assert "## 入库文本" in markdown
    assert "## 识别文本" in markdown
    assert "来源文件" not in markdown
    assert "ASR 模型" not in markdown
    assert "01:51:00" not in markdown


def test_normalize_segments_sorts_by_begin_time() -> None:
    segments = [
        TranscriptSegment("later", begin_time=22_000, end_time=23_000),
        TranscriptSegment("first", begin_time=10_000, end_time=20_000),
        TranscriptSegment("middle", begin_time=20_000, end_time=22_000),
    ]

    normalized = KnowledgeMediaTranscriptionService._normalize_segments(
        segments,
        media_duration_ms=30_000,
    )

    assert [item.text for item in normalized] == ["first", "middle", "later"]


def test_normalize_segments_clamps_invalid_end_time() -> None:
    segments = [
        TranscriptSegment("bad range", begin_time=12_000, end_time=10_000),
    ]

    normalized = KnowledgeMediaTranscriptionService._normalize_segments(
        segments,
        media_duration_ms=30_000,
    )

    assert normalized[0].begin_time == 12_000
    assert normalized[0].end_time == 12_000


def test_normalize_segments_can_scale_second_timestamps_with_duration_hint() -> None:
    segments = [
        TranscriptSegment("first", begin_time=10, end_time=20),
        TranscriptSegment("second", begin_time=20, end_time=30),
    ]

    normalized = KnowledgeMediaTranscriptionService._normalize_segments(
        segments,
        media_duration_ms=31_000,
    )

    assert [(item.begin_time, item.end_time) for item in normalized] == [
        (10_000, 20_000),
        (20_000, 30_000),
    ]


def test_convert_to_wav_reports_missing_audio_stream(monkeypatch, tmp_path) -> None:
    media_path = tmp_path / "video-only.mp4"
    media_path.write_bytes(b"fake mp4")

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=args[0],
            stderr=b"Output file #0 does not contain any stream",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KnowledgeMediaNoRecognizableAudioError):
        KnowledgeMediaTranscriptionService._convert_to_wav(str(media_path))


def test_resolve_asr_model_reads_knowledge_config(monkeypatch) -> None:
    model_info = SimpleNamespace(
        id=42,
        model_name="paraformer-realtime-v2",
        model_type=LLMModelType.ASR.value,
        server_id=7,
        online=True,
        config={},
    )
    server_info = SimpleNamespace(name="Aliyun", type=LLMServerType.QWEN.value, config={"api_key": "sk-test"})

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.media_transcription_service.LLMService.get_knowledge_llm",
        lambda tenant_id=None: KnowledgeLLMConfig(asr_model_id=42),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.media_transcription_service.LLMDao.get_model_by_id",
        lambda model_id: model_info if model_id == 42 else None,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.media_transcription_service.LLMDao.get_server_by_id",
        lambda server_id: server_info if server_id == 7 else None,
    )

    resolved_model, resolved_server = KnowledgeMediaTranscriptionService._resolve_asr_model(tenant_id=1)

    assert resolved_model is model_info
    assert resolved_server is server_info


def test_resolve_asr_model_requires_knowledge_config() -> None:
    with patch(
        "bisheng.knowledge.domain.services.media_transcription_service.LLMService.get_knowledge_llm",
        return_value=KnowledgeLLMConfig(asr_model_id=None),
    ):
        with pytest.raises(NoAsrModelConfigError):
            KnowledgeMediaTranscriptionService._resolve_asr_model(tenant_id=1)


def test_resolve_asr_model_accepts_openai_compatible_provider(monkeypatch) -> None:
    model_info = SimpleNamespace(
        id=43,
        model_name="whisper-large-v3",
        model_type=LLMModelType.ASR.value,
        server_id=8,
        online=True,
        config={},
    )
    server_info = SimpleNamespace(name="Higress", type=LLMServerType.OPENAI.value, config={})
    _patch_model_lookup(monkeypatch, model_info, server_info)

    resolved_model, resolved_server = KnowledgeMediaTranscriptionService._resolve_asr_model(tenant_id=1)

    assert resolved_model is model_info
    assert resolved_server is server_info


def test_resolve_asr_model_rejects_provider_without_asr_client(monkeypatch) -> None:
    model_info = SimpleNamespace(
        id=44,
        model_name="some-asr",
        model_type=LLMModelType.ASR.value,
        server_id=9,
        online=True,
        config={},
    )
    server_info = SimpleNamespace(name="Qianfan", type=LLMServerType.QIAN_FAN.value, config={})
    _patch_model_lookup(monkeypatch, model_info, server_info)

    with pytest.raises(KnowledgeMediaTranscriptionError) as exc_info:
        KnowledgeMediaTranscriptionService._resolve_asr_model(tenant_id=1)

    # The frontend maps this prefix to its "provider not supported" copy.
    assert "does not support ASR provider qianfan" in exc_info.value.message


def _patch_model_lookup(monkeypatch, model_info, server_info) -> None:
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.media_transcription_service.LLMService.get_knowledge_llm",
        lambda tenant_id=None: KnowledgeLLMConfig(asr_model_id=model_info.id),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.media_transcription_service.LLMDao.get_model_by_id",
        lambda model_id: model_info if model_id == model_info.id else None,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.media_transcription_service.LLMDao.get_server_by_id",
        lambda server_id: server_info if server_id == model_info.server_id else None,
    )


def test_split_wav_keeps_short_media_as_one_chunk(tmp_path) -> None:
    wav_path = str(tmp_path / "short.wav")

    chunks = KnowledgeMediaTranscriptionService._split_wav(
        wav_path, str(tmp_path), media_duration_ms=CHUNK_SECONDS * 1000
    )

    assert chunks == [AudioChunk(path=wav_path, offset_ms=0, duration_ms=CHUNK_SECONDS * 1000)]


class _FakeASRClient:
    def __init__(self, transcripts: dict[str, ASRTranscript]) -> None:
        self.transcripts = transcripts
        self.closed = False

    async def transcribe_file(self, wav_path, language=None, model=None):
        return self.transcripts[wav_path]

    async def aclose(self) -> None:
        self.closed = True


def _run_chunks(monkeypatch, client, chunks) -> list[TranscriptSegment]:
    async def fake_init(model_info, server_info):
        return client

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.media_transcription_service.BishengASR.init_asr_client",
        fake_init,
    )
    model_info = SimpleNamespace(model_name="whisper-large-v3")
    return asyncio.run(KnowledgeMediaTranscriptionService._atranscribe_chunks(model_info, None, chunks))


def test_chunk_timestamps_are_shifted_by_chunk_offset(monkeypatch) -> None:
    client = _FakeASRClient(
        {
            "a.wav": ASRTranscript(
                text="first second",
                segments=[
                    ASRSegment("first", begin_ms=1_000, end_ms=4_000),
                    ASRSegment("second", begin_ms=250_000, end_ms=299_000),
                ],
            ),
            "b.wav": ASRTranscript(text="third", segments=[ASRSegment("third", begin_ms=2_000, end_ms=9_000)]),
        }
    )
    chunks = [
        AudioChunk(path="a.wav", offset_ms=0, duration_ms=300_000),
        AudioChunk(path="b.wav", offset_ms=300_000, duration_ms=60_000),
    ]

    segments = _run_chunks(monkeypatch, client, chunks)

    assert [(s.text, s.begin_time, s.end_time) for s in segments] == [
        ("first", 1_000, 4_000),
        ("second", 250_000, 299_000),
        ("third", 302_000, 309_000),
    ]
    assert client.closed


def test_plain_text_transcript_becomes_untimed_segment(monkeypatch) -> None:
    client = _FakeASRClient({"a.wav": ASRTranscript(text="hello world")})

    segments = _run_chunks(monkeypatch, client, [AudioChunk(path="a.wav", offset_ms=0, duration_ms=5_000)])

    assert [(s.text, s.begin_time, s.end_time) for s in segments] == [("hello world", None, None)]
    markdown = KnowledgeMediaTranscriptionService._build_markdown(
        source_file_name="a.mp3", model_name="SenseVoiceSmall", segments=segments
    )
    assert "--:--:--" not in markdown


def test_provider_failure_is_reported_as_asr_request_failed(monkeypatch) -> None:
    class _FailingClient(_FakeASRClient):
        async def transcribe_file(self, wav_path, language=None, model=None):
            raise RuntimeError("413 Request Entity Too Large")

    client = _FailingClient({})

    with pytest.raises(KnowledgeMediaTranscriptionError) as exc_info:
        _run_chunks(monkeypatch, client, [AudioChunk(path="a.wav", offset_ms=0, duration_ms=5_000)])

    assert exc_info.value.message == "ASR request failed: 413 Request Entity Too Large"
    assert client.closed


def test_empty_asr_text_reports_missing_recognizable_audio(monkeypatch, tmp_path) -> None:
    media_path = tmp_path / "silent.mp4"
    wav_path = tmp_path / "silent.wav"
    media_path.write_bytes(b"fake mp4")
    wav_path.write_bytes(b"fake wav")

    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_resolve_asr_model", lambda tenant_id: (None, None))
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_resolve_api_key", lambda server, model: "sk-test")
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_transcript_cache_key", lambda *args: "key")
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_load_cached_transcript", lambda key: None)
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_probe_media_duration_ms", lambda path: 1000)
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_convert_to_wav", lambda path: str(wav_path))
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_transcribe_chunks", lambda *args, **kwargs: [])

    with pytest.raises(KnowledgeMediaNoRecognizableAudioError):
        KnowledgeMediaTranscriptionService.transcribe_media(
            str(media_path),
            source_file_name="silent.mp4",
        )


class _FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.store: dict = {}
        self.fail = fail
        self.expirations: dict = {}

    def get(self, key):
        if self.fail:
            raise RedisConnectionError("redis down")
        return self.store.get(key)

    def set(self, key, value, expiration=3600):
        if self.fail:
            raise RedisConnectionError("redis down")
        self.store[key] = value
        self.expirations[key] = expiration


_SERVICE = "bisheng.knowledge.domain.services.media_transcription_service"


def _prepare_cached_run(monkeypatch, tmp_path, redis, model_update_time=datetime(2026, 9, 1, 8, 0, 0)):
    """Wire transcribe_media with a real media file, fake ASR and fake Redis; return the ASR call log."""
    media_path = tmp_path / "meeting.mp3"
    media_path.write_bytes(b"same audio bytes")
    model_info = SimpleNamespace(id=42, model_name="whisper-large-v3", update_time=model_update_time)
    server_info = SimpleNamespace(type=LLMServerType.OPENAI.value, update_time=datetime(2026, 9, 1, 8, 0, 0))
    calls: list[str] = []

    def fake_transcribe_chunks(model, server, chunks):
        calls.append(model.model_name)
        return [TranscriptSegment("大家好", begin_time=0, end_time=1200)]

    monkeypatch.setattr(f"{_SERVICE}.get_redis_client_sync", lambda: redis)
    monkeypatch.setattr(
        KnowledgeMediaTranscriptionService, "_resolve_asr_model", lambda tenant_id: (model_info, server_info)
    )
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_resolve_api_key", lambda server, model: "sk-test")
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_probe_media_duration_ms", lambda path: 1200)
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_convert_to_wav", lambda path: str(tmp_path / "tmp.wav"))
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_transcribe_chunks", fake_transcribe_chunks)
    return str(media_path), model_info, calls


def test_second_run_reuses_cached_transcript(monkeypatch, tmp_path) -> None:
    redis = _FakeRedis()
    media_path, _, calls = _prepare_cached_run(monkeypatch, tmp_path, redis)

    first = KnowledgeMediaTranscriptionService.transcribe_media(media_path, source_file_name="meeting.mp3", tenant_id=1)
    second = KnowledgeMediaTranscriptionService.transcribe_media(
        media_path, source_file_name="meeting.mp3", tenant_id=1
    )

    # Preview then ingest of the same upload: the model is called once.
    assert calls == ["whisper-large-v3"]
    assert second == first
    assert list(redis.expirations.values()) == [86400]


def test_changed_model_config_misses_cache(monkeypatch, tmp_path) -> None:
    redis = _FakeRedis()
    media_path, model_info, calls = _prepare_cached_run(monkeypatch, tmp_path, redis)

    KnowledgeMediaTranscriptionService.transcribe_media(media_path, source_file_name="meeting.mp3", tenant_id=1)
    model_info.update_time = datetime(2026, 9, 2, 9, 30, 0)
    KnowledgeMediaTranscriptionService.transcribe_media(media_path, source_file_name="meeting.mp3", tenant_id=1)

    assert len(calls) == 2


def test_cache_is_scoped_by_tenant(monkeypatch, tmp_path) -> None:
    redis = _FakeRedis()
    media_path, _, calls = _prepare_cached_run(monkeypatch, tmp_path, redis)

    KnowledgeMediaTranscriptionService.transcribe_media(media_path, source_file_name="meeting.mp3", tenant_id=1)
    KnowledgeMediaTranscriptionService.transcribe_media(media_path, source_file_name="meeting.mp3", tenant_id=2)

    assert len(calls) == 2


def test_empty_transcript_is_not_cached(monkeypatch, tmp_path) -> None:
    redis = _FakeRedis()
    media_path, _, _ = _prepare_cached_run(monkeypatch, tmp_path, redis)
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_transcribe_chunks", lambda *args: [])

    with pytest.raises(KnowledgeMediaNoRecognizableAudioError):
        KnowledgeMediaTranscriptionService.transcribe_media(media_path, source_file_name="meeting.mp3", tenant_id=1)

    # A retry must call the model again instead of replaying "no speech".
    assert redis.store == {}


def test_redis_failure_still_transcribes(monkeypatch, tmp_path) -> None:
    redis = _FakeRedis(fail=True)
    media_path, _, calls = _prepare_cached_run(monkeypatch, tmp_path, redis)

    result = KnowledgeMediaTranscriptionService.transcribe_media(
        media_path, source_file_name="meeting.mp3", tenant_id=1
    )

    assert result.text == "大家好"
    assert calls == ["whisper-large-v3"]
