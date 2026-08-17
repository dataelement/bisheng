"""Pre-publish secret scan — the rule table and its executor (AC-10 / design D5).

Shape and reasoning:

* **A module constant of compiled regexes**, in the same style as
  ``open_api/domain/scopes.py``'s ``OPEN_API_SCOPES``. Not ``detect-secrets`` /
  ``gitleaks``: the repository has zero precedent for either, both add a
  dependency (one of them a binary), and their rule sets are not ours to
  control — while AC-10 requires "the same rule set as an in-platform publish",
  i.e. a rule set this codebase owns. ``sensitive_word``'s Aho-Corasick
  automaton was the other candidate and is literal-match only.
* **This constant *is* the "same rule set"** AC-10 talks about. When PRD-2 adds
  in-platform publishing it imports this module; there is deliberately no
  second copy to keep in sync.
* **A hit never carries the value.** ``{rule_id, name_i18n_key, file, line}``
  and nothing else — not even masked. "First four, last four" masking leaks a
  low-entropy credential outright, and ``file:line`` is already everything
  needed to find it.
* **Skips are reported, never silent.** Binary files and files over
  :data:`MAX_SCAN_FILE_BYTES` are not scanned; a skip that does not appear in
  the report is indistinguishable from a clean pass, which is a false green on
  the one gate whose whole job is to fail closed.
* **No inline suppression comment.** A ``# bisheng:allow-secret`` escape hatch
  would be used to get past the gate long before it is used to silence a false
  positive (design §8). If the generic rule turns out to be noisy the answer is
  a better rule, not an opt-out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bisheng.open_api.domain.models.api_credential import KEY_PREFIX, KEY_SECRET_LENGTH

#: Files above this size are skipped and reported as skipped.
MAX_SCAN_FILE_BYTES = 1024 * 1024

#: Bytes sniffed for a NUL to decide "binary".
_SNIFF_BYTES = 8192

#: Directories that are never part of what gets published, and routinely hold
#: other people's credentials (``.git`` config, npm tokens in a lockfile…).
IGNORED_DIRS: frozenset[str] = frozenset({".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"})

#: Values that look like credentials but are documentation. Checked against the
#: *value* the generic rule captured, never against the whole line.
_PLACEHOLDER_RE = re.compile(r"(?i)^(x{3,}|your[_-]|<.*>|\$\{|change[_-]?me|example)")


@dataclass(frozen=True, slots=True)
class SecretRule:
    """One detection rule. ``pattern`` is matched per line."""

    rule_id: str
    name_i18n_key: str
    pattern: re.Pattern[str]
    description_i18n_key: str
    #: Index of the capture group holding the credential value, when the rule
    #: has one. Only used to run the placeholder allow-list — the value is never
    #: put in the report.
    value_group: int | None = None


#: The rule set. **Every rule needs a positive and a negative sample** in
#: ``test/app_publish/test_secret_rules.py``; the suite iterates this tuple and
#: turns red when one is missing, which is what makes AC-10's "100% of the
#: samples are blocked" a checkable statement rather than a hope.
SECRET_SCAN_RULES: tuple[SecretRule, ...] = (
    SecretRule(
        rule_id="bs_sak",
        name_i18n_key="app_publish.secret_rule.bs_sak.name",
        description_i18n_key="app_publish.secret_rule.bs_sak.desc",
        # Built from F049's constants rather than written out: when the prefix
        # or the secret length changes, this rule follows instead of quietly
        # stopping to match (C6 forbids the hardcoded literal for exactly this).
        pattern=re.compile(rf"\b{re.escape(KEY_PREFIX)}[A-Za-z0-9_\-]{{{KEY_SECRET_LENGTH}}}\b"),
    ),
    SecretRule(
        rule_id="aws_akid",
        name_i18n_key="app_publish.secret_rule.aws_akid.name",
        description_i18n_key="app_publish.secret_rule.aws_akid.desc",
        pattern=re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    SecretRule(
        rule_id="openai_sk",
        name_i18n_key="app_publish.secret_rule.openai_sk.name",
        description_i18n_key="app_publish.secret_rule.openai_sk.desc",
        pattern=re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    ),
    SecretRule(
        rule_id="private_key_pem",
        name_i18n_key="app_publish.secret_rule.private_key_pem.name",
        description_i18n_key="app_publish.secret_rule.private_key_pem.desc",
        pattern=re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----"),
    ),
    SecretRule(
        rule_id="db_conn_string",
        name_i18n_key="app_publish.secret_rule.db_conn_string.name",
        description_i18n_key="app_publish.secret_rule.db_conn_string.desc",
        # Both a user *and* a password have to be in the URL. A DSN carrying
        # only a host is what ordinary configuration looks like, and a scanner
        # that flags it is one developers learn to route around.
        pattern=re.compile(r"\b(mysql|postgresql|postgres|mongodb(\+srv)?|redis|amqp)://[^\s:@/]+:[^\s@/]+@"),
    ),
    SecretRule(
        rule_id="generic_high_entropy",
        name_i18n_key="app_publish.secret_rule.generic_high_entropy.name",
        description_i18n_key="app_publish.secret_rule.generic_high_entropy.desc",
        pattern=re.compile(r"""(?i)(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*["']([^"'\s]{20,})["']"""),
        value_group=2,
    ),
)


@dataclass(slots=True)
class ScanResult:
    """What the scan found and what it did not look at."""

    hits: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    files_scanned: int = 0

    @property
    def files_skipped(self) -> int:
        return len(self.skipped)

    @property
    def blocked(self) -> bool:
        """Any hit blocks the publish (16241). There is no severity ladder this round."""
        return bool(self.hits)

    def to_dict(self) -> dict[str, Any]:
        """The persisted / returned form — ``app_deployment.scan_result`` and the CLI both read this."""
        return {
            "blocked": self.blocked,
            "hits": self.hits,
            "skipped": self.skipped,
            "files_scanned": self.files_scanned,
            "files_skipped": self.files_skipped,
        }


def scan_package(root: Path) -> ScanResult:
    """Scan an unpacked package. Paths in the report are package-relative POSIX paths."""
    result = ScanResult()
    root = Path(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if IGNORED_DIRS.intersection(relative.parts[:-1]):
            continue
        name = relative.as_posix()
        reason = _skip_reason(path)
        if reason is not None:
            result.skipped.append({"file": name, "reason": reason})
            continue
        result.files_scanned += 1
        result.hits.extend(_scan_file(path, name))
    return result


def _skip_reason(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_SCAN_FILE_BYTES:
            return "too_large"
        with open(path, "rb") as handle:
            if b"\x00" in handle.read(_SNIFF_BYTES):
                return "binary"
    except OSError:
        return "unreadable"
    return None


def _scan_file(path: Path, name: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits
    for line_no, line in enumerate(text.splitlines(), start=1):
        for rule in SECRET_SCAN_RULES:
            match = rule.pattern.search(line)
            if match is None:
                continue
            if rule.value_group is not None and _PLACEHOLDER_RE.match(match.group(rule.value_group) or ""):
                continue
            hits.append(
                {
                    "rule_id": rule.rule_id,
                    "name_i18n_key": rule.name_i18n_key,
                    "file": name,
                    "line": line_no,
                }
            )
    return hits
