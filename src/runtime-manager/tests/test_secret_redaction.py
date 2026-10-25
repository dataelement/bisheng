"""Business-secret output coverage, independent of orchestration. AC-68, AC-82, AC-86."""

from runtime_manager.secret_redaction import redact_output


def test_short_nonobvious_and_overlapping_values():
    env = {"COLOR": "a", "ORDER": "abcdef", "MORE": "abc", "TEXT": "密码\n second "}
    result = redact_output("abcdef abc a 密码\n second ", env, list(env))
    for secret in env.values():
        assert secret not in result.replace("<redacted>", "")
    assert result.count("<redacted>") >= 4


def test_missing_sensitive_context_omits_tail():
    assert redact_output("unsafe", {}, ["COLOR"]) == ""
    assert redact_output("ordinary logs", {}, []) == "ordinary logs"


def test_tail_fragments_are_removed_before_truncation():
    assert "secret" not in redact_output("secret trailing", {"COLOR": "prefix-secret"}, ["COLOR"])
    assert not redact_output("trailing prefix-", {"COLOR": "prefix-secret"}, ["COLOR"]).endswith("prefix-")
