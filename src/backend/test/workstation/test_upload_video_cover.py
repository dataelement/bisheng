"""A video uploaded from any chat surface comes back with a poster frame.

Covers were produced only where attachments get parsed — daily chat and
Linsight. A workflow uploads through the same shared endpoint but has no such
parse step, so its videos had no cover and the message bubble showed a bare
"MP4" card while the identical file in daily chat showed a thumbnail.

The whole client chain already carried the field: the uploader reads
`cover_filepath` off the upload response, the send payload keeps it, and the
workflow stores the attachment verbatim. Only the response never had one.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.workstation.domain.services.media_cover_service import WorkstationMediaCoverService

_COVER = "tmp/9f2c_cover.jpg"


def _upload_file(name: str = "bixude.mp4"):
    return SimpleNamespace(filename=name, seek=AsyncMock(), read=AsyncMock(return_value=b""))


async def _cover_for(name: str, *, extract=None, materialize=None):
    with (
        patch.object(
            WorkstationMediaCoverService,
            "materialize_upload_to_temp",
            materialize or AsyncMock(return_value="/tmp/x.mp4"),
        ),
        patch.object(
            WorkstationMediaCoverService,
            "upload_video_cover",
            extract or AsyncMock(return_value=_COVER),
        ),
        patch(
            "bisheng.core.storage.minio.minio_manager.get_minio_storage",
            AsyncMock(return_value=object()),
        ),
        patch.object(WorkstationMediaCoverService, "cleanup_temp") as cleanup,
    ):
        result = await WorkstationMediaCoverService.cover_for_uploaded_video(_upload_file(name), name)
    return result, cleanup


async def test_a_video_upload_gets_a_cover() -> None:
    result, _ = await _cover_for("bixude.mp4")

    assert result == _COVER


@pytest.mark.parametrize("name", ["report.pdf", "notes.txt", "photo.png", "clip.mp3"])
async def test_a_non_video_upload_does_no_work(name) -> None:
    """The endpoint is shared with document uploads; they must pay nothing."""

    materialize = AsyncMock()
    result, _ = await _cover_for(name, materialize=materialize)

    assert result is None
    materialize.assert_not_awaited()


async def test_a_failed_extraction_does_not_fail_the_upload() -> None:
    """Losing a thumbnail is cheap; losing the attachment is not."""

    result, _ = await _cover_for(
        "bixude.mp4",
        extract=AsyncMock(side_effect=RuntimeError("ffmpeg missing")),
    )

    assert result is None


async def test_the_temp_file_is_always_cleaned_up() -> None:
    _, cleanup = await _cover_for(
        "bixude.mp4",
        extract=AsyncMock(side_effect=RuntimeError("ffmpeg missing")),
    )

    cleanup.assert_called_once()


@pytest.mark.parametrize(
    ("name", "expected"),
    [("a.mp4", True), ("a.MOV", True), ("a.webm", True), ("a.pdf", False), ("a", False)],
)
def test_which_names_count_as_video(name, expected) -> None:
    assert WorkstationMediaCoverService.is_video_filename(name) is expected
