from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.portal_course import (
    PortalCourseMediaTooLargeError,
    PortalCourseMediaUnsupportedError,
    PortalCourseProbeFailedError,
    PortalCourseSourceReplaceError,
)
from bisheng.shougang_portal_course.domain.services.media_service import (
    MAX_MEDIA_BYTES,
    PortalCourseMediaService,
)


class FakeUpload:
    def __init__(self, chunks: list[bytes], filename: str = "lesson.bin"):
        self._chunks = iter(chunks)
        self.filename = filename

    async def read(self, _size: int) -> bytes:
        return next(self._chunks, b"")


def _result(
    *,
    container: str,
    video: str | None = None,
    audio: str | None = None,
    duration: str = "1.2",
    streams: list[dict] | None = None,
):
    if streams is None:
        streams = []
        if video:
            streams.append({"codec_type": "video", "codec_name": video})
        if audio:
            streams.append({"codec_type": "audio", "codec_name": audio})
    return subprocess.CompletedProcess(
        args=["ffprobe"],
        returncode=0,
        stdout=json.dumps(
            {
                "format": {"format_name": container, "duration": duration},
                "streams": streams,
            }
        ),
        stderr="",
    )


def _write_mp4(path: Path, brand: bytes = b"isom") -> None:
    path.write_bytes(b"\x00\x00\x00\x18ftyp" + brand + b"\x00" * 32)


def _write_webm(path: Path) -> None:
    path.write_bytes(b"\x1a\x45\xdf\xa3\x42\x82\x84webm" + b"\x00" * 32)


@pytest.mark.parametrize("size", [MAX_MEDIA_BYTES - 1, MAX_MEDIA_BYTES])
def test_media_size_boundary_accepts_at_most_one_gib(size):
    PortalCourseMediaService.ensure_size(size)


def test_media_size_boundary_rejects_one_byte_over():
    with pytest.raises(PortalCourseMediaTooLargeError):
        PortalCourseMediaService.ensure_size(MAX_MEDIA_BYTES + 1)


@pytest.mark.parametrize(
    ("kind", "container", "video", "audio"),
    [
        ("mp4", "mov,mp4,m4a,3gp,3g2,mj2", "h264", "aac"),
        ("mp4", "mov,mp4,m4a,3gp,3g2,mj2", "h264", None),
        ("webm", "matroska,webm", "vp8", "vorbis"),
        ("webm", "matroska,webm", "vp9", "opus"),
    ],
)
def test_probe_accepts_only_browser_compatible_combinations(
    tmp_path,
    kind,
    container,
    video,
    audio,
):
    path = tmp_path / "media"
    (_write_mp4 if kind == "mp4" else _write_webm)(path)
    service = PortalCourseMediaService(storage=AsyncMock(), runner=lambda *a, **k: _result(
        container=container,
        video=video,
        audio=audio,
    ))

    probe = service.probe(path)

    assert probe.extension == kind
    assert probe.duration_seconds == 2
    assert probe.content_type == f"video/{kind}"


@pytest.mark.parametrize(
    ("brand", "audio"),
    [
        pytest.param(b"MSNV", "aac", id="non-legacy-mp4-brand"),
        pytest.param(b"isom", "mp3", id="mp4-mp3-audio"),
        pytest.param(b"qt  ", "aac", id="quicktime-h264-aac"),
        pytest.param(b"qt  ", "mp3", id="quicktime-h264-mp3"),
    ],
)
def test_probe_accepts_compatible_iso_bmff_without_legacy_false_rejections(
    tmp_path,
    brand,
    audio,
):
    path = tmp_path / "media"
    _write_mp4(path, brand=brand)
    service = PortalCourseMediaService(
        storage=AsyncMock(),
        runner=lambda *a, **k: _result(
            container="mov,mp4,m4a,3gp,3g2,mj2",
            video="h264",
            audio=audio,
        ),
    )

    probe = service.probe(path)

    assert probe.extension == "mp4"
    assert probe.content_type == "video/mp4"


def test_probe_ignores_auxiliary_streams_and_attached_cover_art(tmp_path):
    path = tmp_path / "media"
    _write_mp4(path)
    streams = [
        {"codec_type": "video", "codec_name": "h264", "disposition": {}},
        {
            "codec_type": "video",
            "codec_name": "mjpeg",
            "disposition": {"attached_pic": 1},
        },
        {"codec_type": "audio", "codec_name": "aac"},
        {"codec_type": "subtitle", "codec_name": "mov_text"},
        {"codec_type": "data", "codec_name": "tmcd"},
        {"codec_type": "attachment", "codec_name": "ttf"},
    ]
    service = PortalCourseMediaService(
        storage=AsyncMock(),
        runner=lambda *a, **k: _result(
            container="mov,mp4,m4a,3gp,3g2,mj2",
            streams=streams,
        ),
    )

    probe = service.probe(path)

    assert probe.extension == "mp4"


@pytest.mark.parametrize(
    ("header", "container", "video", "audio"),
    [
        ("mp4", "mov,mp4,m4a,3gp,3g2,mj2", "hevc", "aac"),
        ("webm", "matroska,webm", "h264", "opus"),
        ("webm", "matroska,webm", "vp9", "aac"),
    ],
)
def test_probe_rejects_unsupported_codecs(
    tmp_path,
    header,
    container,
    video,
    audio,
):
    path = tmp_path / "media"
    if header == "mp4":
        _write_mp4(path)
    else:
        _write_webm(path)
    service = PortalCourseMediaService(storage=AsyncMock(), runner=lambda *a, **k: _result(
        container=container,
        video=video,
        audio=audio,
    ))

    with pytest.raises(PortalCourseMediaUnsupportedError):
        service.probe(path)


@pytest.mark.parametrize(
    ("brand", "streams", "message_part"),
    [
        pytest.param(
            b"qt  ",
            [{"codec_type": "video", "codec_name": "hevc"}],
            "HEVC/H.265",
            id="quicktime-hevc-video",
        ),
        pytest.param(
            b"qt  ",
            [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "flac"},
            ],
            "FLAC 音频编码",
            id="quicktime-unsupported-audio",
        ),
        pytest.param(
            b"3gp5",
            [{"codec_type": "video", "codec_name": "h264"}],
            "3GP 容器",
            id="3gp-container",
        ),
        pytest.param(
            b"3g2a",
            [{"codec_type": "video", "codec_name": "h264"}],
            "3G2 容器",
            id="3g2-container",
        ),
        pytest.param(
            b"isom",
            [{"codec_type": "video", "codec_name": "hevc"}],
            "HEVC/H.265",
            id="hevc-video",
        ),
        pytest.param(
            b"isom",
            [{"codec_type": "video", "codec_name": "prores"}],
            "ProRes",
            id="prores-video",
        ),
        pytest.param(
            b"isom",
            [{"codec_type": "video", "codec_name": "mpeg4"}],
            "MPEG-4 Visual",
            id="mpeg4-visual-video",
        ),
        pytest.param(
            b"isom",
            [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "video", "codec_name": "h264"},
            ],
            "多个主视频轨",
            id="multiple-primary-video-streams",
        ),
        pytest.param(
            b"isom",
            [
                {
                    "codec_type": "video",
                    "codec_name": "mjpeg",
                    "disposition": {"attached_pic": 1},
                }
            ],
            "未检测到主视频轨",
            id="missing-primary-video-stream",
        ),
        pytest.param(
            b"isom",
            [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "flac"},
            ],
            "FLAC 音频编码",
            id="unsupported-mp4-audio",
        ),
    ],
)
def test_probe_rejects_unsupported_media_with_specific_safe_message(
    tmp_path,
    brand,
    streams,
    message_part,
):
    path = tmp_path / "media"
    _write_mp4(path, brand=brand)
    service = PortalCourseMediaService(
        storage=AsyncMock(),
        runner=lambda *a, **k: _result(
            container="mov,mp4,m4a,3gp,3g2,mj2",
            streams=streams,
        ),
    )

    with pytest.raises(PortalCourseMediaUnsupportedError) as caught:
        service.probe(path)

    assert caught.value.code == 25005
    assert message_part in caught.value.message
    assert str(path) not in caught.value.message


def test_probe_rejects_spoofed_mp4_header_with_specific_safe_message(tmp_path):
    path = tmp_path / "lesson.mp4"
    path.write_bytes(b"not-an-mp4")
    service = PortalCourseMediaService(storage=AsyncMock())

    with pytest.raises(PortalCourseMediaUnsupportedError) as caught:
        service.probe(path)

    assert caught.value.code == 25005
    assert "无法识别视频容器" in caught.value.message
    assert str(path) not in caught.value.message


@pytest.mark.parametrize(
    "runner_error",
    [
        FileNotFoundError(),
        subprocess.TimeoutExpired(cmd="ffprobe", timeout=30),
    ],
)
def test_probe_returns_stable_error_when_ffprobe_is_missing_or_times_out(tmp_path, runner_error):
    path = tmp_path / "media"
    _write_mp4(path)

    def fail(*_args, **_kwargs):
        raise runner_error

    with pytest.raises(PortalCourseProbeFailedError) as caught:
        PortalCourseMediaService(storage=AsyncMock(), runner=fail).probe(path)

    assert str(caught.value) == PortalCourseProbeFailedError.Msg
    if str(runner_error):
        assert str(runner_error) not in str(caught.value)


async def test_storage_failure_is_sanitized_and_temp_file_is_removed(tmp_path):
    storage = AsyncMock()
    storage.bucket = "bisheng"
    storage.put_object.side_effect = OSError("/secret/minio/path")
    service = PortalCourseMediaService(
        storage=storage,
        runner=lambda *a, **k: _result(
            container="mov,mp4,m4a,3gp,3g2,mj2",
            video="h264",
            audio="aac",
        ),
        temp_dir=tmp_path,
    )

    with pytest.raises(PortalCourseSourceReplaceError) as caught:
        await service.save_upload(
            FakeUpload([b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32]),
            tenant_id=1,
            course_id="c" * 32,
            video_id="v" * 32,
        )

    assert str(caught.value) == PortalCourseSourceReplaceError.Msg
    assert "/secret/minio/path" not in str(caught.value)
    assert list(tmp_path.iterdir()) == []


async def test_streaming_upload_stops_before_storage_and_removes_temp_file(tmp_path):
    storage = AsyncMock()
    storage.bucket = "bisheng"
    service = PortalCourseMediaService(
        storage=storage,
        runner=lambda *a, **k: _result(
            container="mov,mp4,m4a,3gp,3g2,mj2",
            video="h264",
            audio="aac",
        ),
        max_bytes=4,
        temp_dir=tmp_path,
    )

    with pytest.raises(PortalCourseMediaTooLargeError):
        await service.save_upload(
            FakeUpload([b"1234", b"5"]),
            tenant_id=1,
            course_id="c" * 32,
            video_id="v" * 32,
        )

    storage.put_object.assert_not_awaited()
    assert list(tmp_path.iterdir()) == []
