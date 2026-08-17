"""T012 — the secret-scan rule set (AC-10's direct carrier).

AC-10 promises "100% of the samples in the rule set are blocked". That promise
is only meaningful if the samples live *with* the rules, so this file iterates
``SECRET_SCAN_RULES`` and demands a positive and a negative sample per rule:
adding a rule without samples turns the suite red, which is the only mechanism
that keeps the promise true as the rule set grows.

The second promise — **the matched value never leaves the scanner** — is
asserted by serialising the whole report and searching it for the sample
secret. Not even a masked form is allowed: any "first 4, last 4" masking leaks a
low-entropy key outright, and ``file:line`` is already enough to find it.

Two failure modes this file is built to catch:

* **A rule that fires on normal configuration.** A connection string with only a
  host in it is how every ``config.yaml`` in the world looks; if that trips the
  scanner, developers learn to route around the gate.
* **A silently skipped file.** Big files and binaries are skipped for
  performance, and a skip that is not reported is indistinguishable from a pass.

⚠️ ``scripts/arch-guard.sh`` RULE-7 flags this file as "hardcoded credentials".
That is correct and expected: the samples below *are* credentials in shape.
None of them is real — ``AKIAIOSFODNN7EXAMPLE`` is AWS's published example key,
and the rest are keyboard noise of the right length. Do not "fix" the warning by
weakening the samples; a scanner tested against strings that do not look like
secrets is not tested at all.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio

#: ``{rule_id: (positive, negative)}`` — the sample pairs AC-10 is measured on.
#: The positive sample must be blocked; the negative must not be. Keys are
#: checked against ``SECRET_SCAN_RULES`` so the two can never drift.
SAMPLES: dict[str, tuple[str, str]] = {
    "bs_sak": (
        'KEY = "bs-sak-Ab3dEf6hIj9lMn2pQr5tUv8xYz1cDe4gHi7kLm0nOp3"',
        'KEY = os.environ["BISHENG_SAK"]  # bs-sak- keys are read from the environment',
    ),
    "aws_akid": (
        'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"',
        'AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")',
    ),
    "openai_sk": (
        'client = OpenAI(api_key="sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD")',
        'client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])',
    ),
    "private_key_pem": (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----",
        "-----BEGIN CERTIFICATE-----\nMIIDdz...\n-----END CERTIFICATE-----",
    ),
    "db_conn_string": (
        'DSN = "mysql://appuser:s3cr3tP4ss@db.internal:3306/appdb"',
        'DSN = "mysql://db.internal:3306/appdb"',
    ),
    "generic_high_entropy": (
        'api_key = "Zk8vQ2mN4pR7tW1yB5xC9eH3jL6sD0fG"',
        'api_key = "your_api_key_here_placeholder"',
    ),
}


def _rules():
    from bisheng.app_publish.domain.services.secret_scanner import SECRET_SCAN_RULES

    return SECRET_SCAN_RULES


def _scan(tmp_path, files: dict[str, str]):
    from bisheng.app_publish.domain.services.secret_scanner import scan_package

    root = tmp_path / "pkg"
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    return scan_package(root)


# ---------------------------------------------------------------------------
# The rule set as a whole
# ---------------------------------------------------------------------------


async def test_every_rule_has_positive_and_negative_sample():
    """Adding a rule without samples must break the build — that is what keeps AC-10 honest."""
    rule_ids = [rule.rule_id for rule in _rules()]
    assert len(rule_ids) == len(set(rule_ids)), "rule ids must be unique"
    assert set(rule_ids) == set(SAMPLES), (
        f"rules without samples: {sorted(set(rule_ids) - set(SAMPLES))}; "
        f"samples without rules: {sorted(set(SAMPLES) - set(rule_ids))}"
    )
    for rule in _rules():
        assert rule.name_i18n_key and rule.description_i18n_key


@pytest.mark.parametrize("rule_id", sorted(SAMPLES))
async def test_every_positive_sample_blocks_publish(tmp_path, rule_id):
    positive, _ = SAMPLES[rule_id]
    result = _scan(tmp_path, {"app/config.py": positive})
    assert result.blocked is True
    assert rule_id in {hit["rule_id"] for hit in result.hits}, f"{rule_id} did not match its own positive sample"


@pytest.mark.parametrize("rule_id", sorted(SAMPLES))
async def test_every_negative_sample_passes(tmp_path, rule_id):
    _, negative = SAMPLES[rule_id]
    result = _scan(tmp_path, {"app/config.py": negative})
    assert rule_id not in {hit["rule_id"] for hit in result.hits}, (
        f"{rule_id} fired on ordinary configuration; developers route around a gate that cries wolf"
    )


async def test_output_never_contains_secret_value(tmp_path):
    """AC-10's hard promise — not the value, not a masked value, not a prefix."""
    secret = "Zk8vQ2mN4pR7tW1yB5xC9eH3jL6sD0fG"
    result = _scan(tmp_path, {"app/settings.py": f'api_key = "{secret}"\n'})
    serialized = json.dumps(result.to_dict(), ensure_ascii=False)

    assert result.blocked is True
    assert secret not in serialized
    assert secret[:8] not in serialized, "a masked prefix is still a leak on a low-entropy key"
    assert secret[-8:] not in serialized


async def test_bs_sak_rule_follows_key_prefix_constant():
    """The rule is *built from* F049's constants, so changing the prefix cannot leave it behind (C6)."""
    from bisheng.open_api.domain.models.api_credential import KEY_PREFIX, KEY_SECRET_LENGTH

    rule = next(rule for rule in _rules() if rule.rule_id == "bs_sak")
    # Asserted by behaviour rather than by substring: the pattern is built with
    # ``re.escape``, so the literal prefix does not appear verbatim in it. What
    # must hold is that a key of exactly the shape F049 issues matches, and one
    # a character short does not.
    assert rule.pattern.search(f"{KEY_PREFIX}{'a' * KEY_SECRET_LENGTH}")
    assert not rule.pattern.search(f"{KEY_PREFIX}{'a' * (KEY_SECRET_LENGTH - 1)} ")
    assert not rule.pattern.search(f"bs-xxx-{'a' * KEY_SECRET_LENGTH}")


async def test_db_conn_string_requires_user_and_password(tmp_path):
    """Host-only DSNs are normal configuration; only credentials embedded in the URL are a finding."""
    result = _scan(
        tmp_path,
        {
            "ok.py": 'A = "postgresql://db.internal:5432/app"\nB = "redis://cache:6379/0"\n',
            "bad.py": 'C = "postgresql://admin:hunter2@db.internal:5432/app"\n',
        },
    )
    files = {hit["file"] for hit in result.hits if hit["rule_id"] == "db_conn_string"}
    assert files == {"bad.py"}


async def test_generic_high_entropy_skips_placeholders(tmp_path):
    placeholders = "\n".join(
        [
            'password = "your_password_here_placeholder"',
            'token = "<REPLACE_WITH_YOUR_TOKEN_VALUE>"',
            'secret = "${APP_SECRET_FROM_ENVIRONMENT}"',
            'api_key = "change_me_before_deploying_this"',
            'password = "example_value_for_documentation"',
            'token = "xxxxxxxxxxxxxxxxxxxxxxxxxxxx"',
        ]
    )
    result = _scan(tmp_path, {"README.example.py": placeholders})
    assert [hit for hit in result.hits if hit["rule_id"] == "generic_high_entropy"] == []


async def test_binary_file_skipped_by_null_byte_sniff(tmp_path):
    from bisheng.app_publish.domain.services.secret_scanner import scan_package

    root = tmp_path / "pkg"
    root.mkdir(parents=True)
    (root / "logo.bin").write_bytes(b"\x00\x01\x02" + b'AKIAIOSFODNN7EXAMPLE"' * 10)
    result = scan_package(root)
    assert result.hits == []
    assert "logo.bin" in {item["file"] for item in result.skipped}
    assert {item["reason"] for item in result.skipped} == {"binary"}


async def test_large_file_marked_skipped_not_silent(tmp_path):
    """A silently skipped file is indistinguishable from a clean one — that is a false pass."""
    from bisheng.app_publish.domain.services.secret_scanner import MAX_SCAN_FILE_BYTES, scan_package

    root = tmp_path / "pkg"
    root.mkdir(parents=True)
    (root / "big.py").write_text("x = 1\n" * (MAX_SCAN_FILE_BYTES // 6 + 10), encoding="utf-8")
    result = scan_package(root)
    assert {"file": "big.py", "reason": "too_large"} in result.skipped
    assert result.files_skipped == 1


async def test_ignored_directories_are_not_scanned(tmp_path):
    """``.git`` and friends hold other people's secrets and are not part of what gets published."""
    result = _scan(
        tmp_path,
        {
            ".git/config": 'password = "Zk8vQ2mN4pR7tW1yB5xC9eH3jL6sD0fG"',
            "node_modules/lib/x.js": 'const t = "sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD";',
            "app.py": "print('ok')\n",
        },
    )
    assert result.hits == []
    assert result.files_scanned == 1


async def test_hit_report_shape_is_file_and_line_only(tmp_path):
    """``{rule_id, name_i18n_key, file, line}`` — enough to find it, not enough to leak it (AC-10 / AC-11)."""
    result = _scan(tmp_path, {"pkg/deep/conf.py": "\n\n" + 'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"\n'})
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert set(hit) == {"rule_id", "name_i18n_key", "file", "line"}
    assert hit["file"] == "pkg/deep/conf.py", "the path is package-relative and POSIX, so it is the same on any host"
    assert hit["line"] == 3
