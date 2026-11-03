"""The receive-side release-notes contract (also implemented by the standalone CLI)."""

from bisheng.common.errcode.app_publish import AppReleaseNotesInvalidError

MAX_RELEASE_NOTES_CODEPOINTS = 2000
RELEASE_NOTES_CONTRACT_VERSION = 1


def normalize_release_notes(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > MAX_RELEASE_NOTES_CODEPOINTS:
        raise AppReleaseNotesInvalidError(
            details={"reason": "too_long", "max_codepoints": MAX_RELEASE_NOTES_CODEPOINTS}
        )
    return normalized or None
