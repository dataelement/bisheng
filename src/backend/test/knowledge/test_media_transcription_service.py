import subprocess

import pytest

from bisheng.common.errcode.knowledge import KnowledgeMediaNoRecognizableAudioError
from bisheng.knowledge.domain.services.media_transcription_service import (
    KnowledgeMediaTranscriptionService,
    TranscriptSegment,
)


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
    assert (
        "[00:00:06 - 00:00:10] My entire life's been spent only in one industry."
        in markdown
    )
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


def test_empty_asr_text_reports_missing_recognizable_audio(monkeypatch, tmp_path) -> None:
    media_path = tmp_path / "silent.mp4"
    wav_path = tmp_path / "silent.wav"
    media_path.write_bytes(b"fake mp4")
    wav_path.write_bytes(b"fake wav")

    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_resolve_asr_model", lambda tenant_id: (None, None))
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_resolve_api_key", lambda server, model: "sk-test")
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_probe_media_duration_ms", lambda path: 1000)
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_convert_to_wav", lambda path: str(wav_path))
    monkeypatch.setattr(KnowledgeMediaTranscriptionService, "_call_aliyun_asr", lambda *args, **kwargs: [])

    with pytest.raises(KnowledgeMediaNoRecognizableAudioError):
        KnowledgeMediaTranscriptionService.transcribe_media(
            str(media_path),
            source_file_name="silent.mp4",
        )
