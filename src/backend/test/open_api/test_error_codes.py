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
        {26008, 26009, 26011, 26012, 26013, 26014, 26028, *range(26032, 26040), *range(26044, 26050)}
    )
