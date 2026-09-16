from bisheng.common.errcode import open_api

EXPECTED_CODES = {
    26001,
    26002,
    26003,
    26004,
    26005,
    26006,
    26007,
    26010,
    26015,
    26016,
    26017,
    26018,
    26019,
    26020,
    26021,
    26022,
    26023,
    26024,
    26025,
    26026,
    26027,
    26029,
    26030,
    26031,
    26040,
    26041,
    26042,
    26043,
    26044,
    26050,
    26051,
    # F055 AC-52: a hosted application reaching a v2 endpoint that executes as a
    # natural person. Its scopes come from a capability declaration, and the one
    # that declaration derives (``knowledge:read``) also admits six neighbouring
    # routes that would run as the application's owner.
    26052,
}


def test_only_designated_open_api_error_codes_are_implemented():
    actual = {
        value.Code
        for value in vars(open_api).values()
        if isinstance(value, type)
        and value is not open_api.OpenApiAuthError
        and issubclass(value, open_api.OpenApiAuthError)
    }
    assert actual == EXPECTED_CODES


def test_reserved_and_removed_codes_are_not_reused():
    assert EXPECTED_CODES.isdisjoint(
        {26008, 26009, 26011, 26012, 26013, 26014, 26028, *range(26032, 26040), *range(26045, 26050)}
    )


def test_mcp_face_codes_are_in_263_band_and_have_three_language_copy():
    """F052 module 263 — band, annotation form, and locale copy in one assertion.

    The annotation form matters on its own: ``check-i18n.mjs`` only recognises
    ``Code: int = NNNNN``, so a class written the ``open_api.py`` way would ship
    with no copy and still pass CI.
    """

    import json
    from pathlib import Path

    from bisheng.common.errcode import mcp_face

    codes = {
        value.Code
        for value in vars(mcp_face).values()
        if isinstance(value, type) and issubclass(value, mcp_face.McpFaceError)
    }
    assert codes, "module 263 lost every error code"
    assert all(26300 <= code <= 26339 for code in codes), sorted(codes)
    assert codes.isdisjoint(EXPECTED_CODES), "263 must never collide with the 260 band"

    source = Path(mcp_face.__file__).read_text(encoding="utf-8")
    for code in codes:
        assert f"Code: int = {code}" in source, f"{code} must be declared with the ': int' annotation"

    locales = Path(__file__).resolve().parents[3] / "frontend/packages/locales/src/api_errors"
    for language in ("zh-Hans", "en", "ja"):
        copy = json.loads((locales / f"{language}.json").read_text(encoding="utf-8"))
        missing = {code for code in codes if not copy.get(str(code))}
        assert not missing, f"{language} is missing copy for {sorted(missing)}"
