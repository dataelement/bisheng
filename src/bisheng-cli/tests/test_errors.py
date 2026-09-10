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
    delegate_refusal,
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


def test_26016_and_26051_both_say_delegate_only_and_never_ask_for_a_header() -> None:
    """INV-31: the two gates, one verdict.

    `26016` is where a delegate-only key actually lands during `bisheng login`
    (`whoami` requires no scope, so the entrance gate waves it through and the
    delegation resolver rejects it), and its server-side sentence — "send
    X-On-Behalf-Of" — is advice no CLI caller can take: the CLI never sends
    identity headers on any command. `26051` is the entrance gate itself on
    `deploy` / `logs`. Both must read as "this key is the wrong kind".
    """
    for code in (26016, 26051):
        err = _err(code, "X-On-Behalf-Of is required for a delegated credential")
        assert err.exit_code == EXIT_FORBIDDEN
        assert "委托" in err.message and "本地开发" in err.message
        assert "另外签发" in err.next_step
        # The platform sentence is still echoed under 平台信息 (三部分，缺一不可);
        # what must not happen is the CLI's own advice repeating it.
        assert "X-On-Behalf-Of" not in err.message + err.next_step
        assert "X-On-Behalf-Of" in render_human(err)


def test_delegate_refusal_reads_identically_at_all_three_gates() -> None:
    # The CLI-side check in `login`, 26016 and 26051 are one product rule. Three
    # wordings for it would read as three different problems.
    local = delegate_refusal()
    for code in (26016, 26051):
        err = _err(code)
        assert (err.message, err.next_step) == (local.message, local.next_step)
        assert err.exit_code == local.exit_code


def test_delegate_only_key_is_not_a_defect_and_not_an_unknown_code() -> None:
    # 18 says "stop and file a bug", 19 says "read the message, maybe retry with
    # different arguments". Neither fits: the key is simply the wrong kind, and
    # the fix is a new key from an administrator.
    for code in (26016, 26051):
        assert ERROR_EXIT_CODES[code] == EXIT_FORBIDDEN
        assert ERROR_EXIT_CODES[code] not in (EXIT_DEFECT, EXIT_UNKNOWN_CODE, EXIT_INTERNAL)


def test_26002_covers_the_disabled_account_case_it_actually_receives() -> None:
    """The server folds four causes into 26002, and the copy has to say so.

    `credential_validator.resolve_service_account` raises
    `OpenApiCredentialInvalidError` — 26002 — when the account behind the key is
    missing, disabled or in another tenant. The separate 26027 that F049 raised
    on this path survives only on the management face (issuing a key), which no
    CLI command calls. A next step reading only "get a new key" therefore sends
    the holder of a disabled account round a loop that cannot terminate.
    """
    texts = {code: render_human(_err(code)) for code in (26001, 26002, 26027)}
    assert len(set(texts.values())) == 3
    for code in texts:
        assert ERROR_EXIT_CODES[code] == EXIT_AUTH
    assert "停用" in texts[26002]
    assert "换一把密钥没有用" in texts[26027]


def test_personal_token_codes_are_registered_not_generic_403_or_401() -> None:
    # beta2 authenticates `bs-pat-` tokens on the same endpoints, so the CLI can
    # receive these. Unregistered they degraded by HTTP status into "ask your
    # admin about the permission bits" / "check whether the key expired", which
    # is the wrong investigation: the problem is the credential *kind*.
    disabled, holder_gone = _err(26040, http_status=403), _err(26043, http_status=401)
    assert (disabled.exit_code, holder_gone.exit_code) == (EXIT_FORBIDDEN, EXIT_AUTH)
    for err in (disabled, holder_gone):
        assert "个人" in err.message
        assert "bs-sak-" in err.next_step


def test_26030_marked_retryable() -> None:
    err = _err(26030, http_status=503)
    assert err.exit_code == EXIT_UNREACHABLE
    assert "可重试" in render_human(err)


def test_16207_maps_to_layer_not_enabled() -> None:
    err = _err(16207)
    assert err.exit_code == EXIT_NOT_ENABLED
    assert "应用工场" in render_human(err)


def test_build_failure_prints_the_log_excerpt_it_tells_you_to_read() -> None:
    """The hints say "look at the log excerpt"; there has to be one to look at.

    ``details`` used to reach ``--json`` only, so in a terminal that advice
    pointed at nothing and the natural next move was to re-run the same deploy
    unchanged.
    """
    err = _err(
        16227,
        "依赖构建失败",
        details={
            "reason": "build_network_blocked",
            "tail": [
                "Step 5/17 : RUN pip install -r requirements.txt",
                "ERROR: No matching distribution found for fastapi",
            ],
        },
        hints=["构建容器连不上任何软件源, 这是构建环境的网络问题, 与 requirements.txt 无关"],
    )

    text = render_human(err)

    assert "No matching distribution found for fastapi" in text
    assert "构建环境的网络问题" in text


def test_a_failure_without_a_log_excerpt_prints_no_empty_section() -> None:
    """Most codes carry no ``tail``; they must not grow a dangling header."""
    text = render_human(_err(26003, "scope missing", details={"required": "app:manage"}))

    assert "构建日志" not in text


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


def test_26004_reads_as_delegation_refused_and_still_points_off_the_key() -> None:
    """26004's meaning moved; its next step had to move with it.

    Under F049 it meant "any identity-passing header at all". beta2 raises it
    from `identity_service.resolve_request_identity` for a request that *did*
    carry `X-On-Behalf-Of` and whose delegation was refused — no `delegate` bit,
    or a target outside the key's delegate scope. What survives unchanged is the
    part the caller acts on: this CLI sends no identity headers on any command,
    so the header came from somewhere else on the path, and neither the key nor
    its permission bits are the thing to go and change.
    """
    text = render_human(_err(26004))
    assert "委托" in text
    assert "X-On-Behalf-Of" in text
    assert "网关" in text or "代理" in text
    assert "CLI 从不发送" in text
    # The head sentence now names the key, because that is what the server's
    # verdict is about ("this key has no delegate bit"). What must not happen is
    # the *next step* sending the reader off to change it: no CLI key delegates,
    # so no key change and no permission bit can produce a different outcome.
    next_step = _err(26004).next_step
    assert "改密钥或权限位都不解决" in next_step


def test_26031_is_reported_as_a_platform_defect() -> None:
    text = render_human(_err(26031, http_status=500))
    assert "平台" in text and "缺陷" in text
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
