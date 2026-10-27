"""Module 263 contract: band, annotation style, three-language copy (F052 T001)."""

import json
import re
from pathlib import Path

from bisheng.common.errcode import mcp_face

LOCALE_DIR = Path(__file__).resolve().parents[3] / "frontend" / "packages" / "locales" / "src" / "api_errors"
LOCALES = ("zh-Hans.json", "en.json", "ja.json")

#: The same regex ``src/frontend/scripts/check-i18n.mjs`` uses to collect
#: backend codes. A subclass written ``Code = 26301`` is invisible to it, so a
#: missing translation would sail through CI — assert the annotated form here.
ANNOTATED_CODE = re.compile(r"Code:\s*int\s*=\s*(\d+)")


def implemented_codes() -> set[int]:
    return {
        value.Code
        for value in vars(mcp_face).values()
        if isinstance(value, type) and value is not mcp_face.McpFaceError and issubclass(value, mcp_face.McpFaceError)
    }


def test_mcp_face_codes_are_in_263_band_and_have_three_language_copy():
    codes = implemented_codes() | {mcp_face.McpFaceError.Code}
    assert codes
    assert all(26300 <= code <= 26339 for code in codes), sorted(codes)

    source = Path(mcp_face.__file__).read_text(encoding="utf-8")
    assert {int(match) for match in ANNOTATED_CODE.findall(source)} == codes

    for name in LOCALES:
        copy = json.loads((LOCALE_DIR / name).read_text(encoding="utf-8"))
        missing = {code for code in codes if not copy.get(str(code))}
        assert not missing, f"{name} is missing copy for {sorted(missing)}"


def test_mcp_face_does_not_squat_the_open_api_260_band():
    """263 is its own module; 260's reserved holes stay reserved."""
    assert implemented_codes().isdisjoint(range(26000, 26100))


def test_every_mcp_face_code_declares_a_real_transport_status():
    for value in vars(mcp_face).values():
        if not isinstance(value, type) or not issubclass(value, mcp_face.McpFaceError):
            continue
        assert 400 <= value.http_status <= 599, value


def test_unreachable_and_revoked_statuses_keep_their_meaning():
    """404 for "unreachable" (same answer as "absent"), 409 for "revoked"."""
    assert mcp_face.KnowledgeUnreachableError.http_status == 404
    assert mcp_face.KnowledgeCapabilityRevokedError.http_status == 409
    assert mcp_face.RetrievalIdentityMissingError.http_status == 403
    assert mcp_face.RetrievalScopeTooLargeError.http_status == 400
