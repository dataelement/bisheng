"""T003 — the exit-code table and the error translation on top of it.

The table's dividing line is **what the developer (or their agent) does next**,
not how bad the failure is. Two codes whose next action differs must land on
different exit codes; that is the whole reason this file exists.
"""

from __future__ import annotations

import pytest

from bisheng_cli.errors import (
    ERROR_EXIT_CODES,
    ERROR_HINTS,
    EXIT_AUTH,
    EXIT_CAPACITY,
    EXIT_DEFECT,
    EXIT_FORBIDDEN,
    EXIT_INTERNAL,
    EXIT_LOCAL_INVALID,
    EXIT_NOT_ENABLED,
    EXIT_PRECHECK_FAILED,
    EXIT_SCENE_MISSING,
    EXIT_UNKNOWN_CODE,
    EXIT_UNREACHABLE,
    CliError,
    error_from_platform,
    render_human,
)
from tests.helpers.platform_mock import FAKE_KEY


def _err(code: int, message: str = "server said so", **kw) -> CliError:
    return error_from_platform(code, message, **kw)


def test_exit_code_table_is_total() -> None:
    assert set(ERROR_HINTS) == set(ERROR_EXIT_CODES)
    for code, (human, next_step) in ERROR_HINTS.items():
        assert human.strip(), f"{code} has no human sentence"
        assert next_step.strip(), f"{code} has no next step"


def test_16225_and_16226_map_to_different_codes_and_different_next_step() -> None:
    scene, capacity = _err(16225), _err(16226)
    assert scene.exit_code == EXIT_SCENE_MISSING == 13
    assert capacity.exit_code == EXIT_CAPACITY == 14
    assert scene.next_step != capacity.next_step


def test_16231_and_16230_next_step_is_delete_capabilities_not_ask_admin() -> None:
    for code in (16230, 16231):
        err = _err(code)
        assert err.exit_code == EXIT_PRECHECK_FAILED == 10
        assert err.exit_code != EXIT_NOT_ENABLED
        assert "capabilities" in err.next_step


def test_16203_next_step_points_to_package_root_not_create_manifest() -> None:
    err = _err(16203)
    assert err.exit_code == EXIT_LOCAL_INVALID
    assert "包根" in err.next_step or "PATH" in err.next_step
    assert "创建" not in err.next_step


def test_26003_prints_required_scope_verbatim() -> None:
    # data.required is a single string; ", ".join() on it would print "a, p, p, :…".
    err = _err(26003, "scope missing", details={"exception": "scope missing", "required": "app:manage"})
    assert err.exit_code == EXIT_FORBIDDEN
    assert "app:manage" in render_human(err)


def test_26001_26002_26027_are_distinguishable() -> None:
    # Only three. 26002 alone covers unknown / revoked / expired — the server
    # gives no signal that separates those three, so the CLI must not pretend to.
    texts = {code: render_human(_err(code)) for code in (26001, 26002, 26027)}
    assert len(set(texts.values())) == 3
    for code in texts:
        assert ERROR_EXIT_CODES[code] == EXIT_AUTH


def test_26030_marked_retryable() -> None:
    err = _err(26030, http_status=503)
    assert err.exit_code == EXIT_UNREACHABLE
    assert "可重试" in render_human(err)


def test_16207_maps_to_layer_not_enabled() -> None:
    err = _err(16207)
    assert err.exit_code == EXIT_NOT_ENABLED
    assert "应用工场" in render_human(err)


def test_unknown_code_falls_back_to_exit_19_not_exit_1() -> None:
    err = _err(16999, "brand new failure")
    assert err.exit_code == EXIT_UNKNOWN_CODE == 19
    assert err.exit_code != EXIT_INTERNAL
    text = render_human(err)
    assert "16999" in text and "brand new failure" in text


def test_161_segment_codes_are_registered_not_unknown() -> None:
    # CON-8: deploy / logs consume F054's 161 segment too.
    assert _err(16121).exit_code == EXIT_UNREACHABLE  # orchestrator down != app missing
    assert _err(16101).exit_code == EXIT_LOCAL_INVALID
    for code in (16121, 16101):
        assert _err(code).exit_code != EXIT_UNKNOWN_CODE


@pytest.mark.parametrize(
    ("http_status", "expected"),
    [
        (503, EXIT_UNREACHABLE),
        (502, EXIT_UNREACHABLE),
        (504, EXIT_UNREACHABLE),
        (401, EXIT_AUTH),
        (403, EXIT_FORBIDDEN),
    ],
)
def test_unknown_code_with_5xx_degrades_to_retryable_not_19(http_status: int, expected: int) -> None:
    # FGA / DB faults surface as HTTP 503 + code 19002; keying only on the code
    # would send the user off to check their key.
    err = _err(19002, "fga unavailable", http_status=http_status)
    assert err.exit_code == expected


def test_unknown_code_without_usable_http_status_falls_to_19() -> None:
    assert _err(19002, "weird", http_status=400).exit_code == EXIT_UNKNOWN_CODE


def test_26004_and_26031_are_reported_as_platform_or_cli_defect() -> None:
    cli_defect = render_human(_err(26004))
    platform_defect = render_human(_err(26031, http_status=500))
    assert "CLI" in cli_defect and "缺陷" in cli_defect
    assert "平台" in platform_defect and "缺陷" in platform_defect
    for text in (cli_defect, platform_defect):
        assert "密钥" not in text.split("下一步")[0]


def test_defect_class_gets_its_own_exit_code_not_1_or_19() -> None:
    # The exit code exists so a caller can pick its next move without reading
    # prose. On 1 it may retry (the CLI crashed); on 19 it may retry with other
    # arguments (unknown code, read the message). For these two, retrying and
    # changing arguments are both useless — that is a third action, so it is a
    # third code. 19 would also be a lie: these codes are registered.
    assert _err(26004).exit_code == EXIT_DEFECT == 18
    assert _err(26031, http_status=500).exit_code == EXIT_DEFECT
    for code in (26004, 26031):
        assert _err(code).exit_code not in (EXIT_INTERNAL, EXIT_UNKNOWN_CODE)


def test_registered_code_wins_over_5xx_degradation() -> None:
    # 26031 arrives with HTTP 500. The 5xx degradation rule only applies to
    # codes with no entry; letting it override a registered mapping would turn
    # "report this defect" into "retry later", which never succeeds.
    assert _err(26031, http_status=500).exit_code != EXIT_UNREACHABLE


def test_delegate_rejection_shape_matches_server_side_rejection() -> None:
    from bisheng_cli.errors import delegate_refusal

    local = delegate_refusal()
    remote = _err(26003, "delegate key", details={"exception": "delegate key", "required": "delegate"})
    assert local.exit_code == remote.exit_code == EXIT_FORBIDDEN
    assert "委托" in render_human(local)


def test_no_error_text_contains_key_material() -> None:
    for code in sorted(ERROR_HINTS):
        err = _err(code, f"server echoed {FAKE_KEY}", details={"key": FAKE_KEY}, hints=[f"try {FAKE_KEY}"])
        assert FAKE_KEY not in render_human(err)
    unknown = _err(19999, f"leak {FAKE_KEY}")
    assert FAKE_KEY not in render_human(unknown)
