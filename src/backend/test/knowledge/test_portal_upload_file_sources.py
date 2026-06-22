from bisheng.knowledge.domain.models.knowledge_file import (
    FileSource,
    PORTAL_USER_UPLOAD_FILE_SOURCES,
)


def test_portal_user_upload_file_sources_include_transcript_media() -> None:
    assert FileSource.SPACE_UPLOAD.value in PORTAL_USER_UPLOAD_FILE_SOURCES
    assert FileSource.AUDIO_TRANSCRIPT.value in PORTAL_USER_UPLOAD_FILE_SOURCES
    assert FileSource.VIDEO_TRANSCRIPT.value in PORTAL_USER_UPLOAD_FILE_SOURCES
    assert FileSource.WEB_LINK.value not in PORTAL_USER_UPLOAD_FILE_SOURCES
    assert FileSource.CHANNEL.value not in PORTAL_USER_UPLOAD_FILE_SOURCES
