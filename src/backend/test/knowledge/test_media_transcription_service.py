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
