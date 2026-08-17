"""Which files go into the package: three layers, from innermost outward.

1. **Structural excludes**, independent of any ignore file.
   *Hard* ones (`.git/`, `node_modules/`, `.venv/`, caches, `.bisheng/`) cannot be
   taken back, because their content is wrong or meaningless on the target
   machine no matter what the developer intends.
   *Soft* ones (`*.sqlite`, `dist/`, `build/`, local attachment dirs) are excluded
   by default but a `!` line in `.bishengignore` gets them back. `dist/` is soft on
   purpose: existing python3.11 apps commonly serve a front-end bundle from there,
   and hard-excluding it strips the app silently — the failure surfaces at probe
   time and sends the investigation after "the platform build".
2. **`.gitignore` semantics.** In a git repo with git on PATH we ask git
   (`git ls-files -c -o --exclude-standard -z`): zero dependencies and 100% of the
   semantics, for free. Otherwise a hand-written subset parser, and the CLI *says
   so* in its output so the developer knows complex rules may need restating.
3. **`.bishengignore`** — same syntax, loaded last, highest priority. The escape
   hatch for whatever the subset parser cannot express.

Why not `fnmatch` for layer 2: its `*` crosses `/` and it has no `**` at all (the
comment in `linsight/.../workspace_backend.py` records both). This repo already
lost time to that once, with a `glob("/uploads/**/*.xlsx")` that matched nothing
for months. Why not `pathspec`: one more air-gapped install link bought only for
projects that are not under git — the case where we are least likely to be right
about the rules anyway.

Known subset limitation: git refuses to re-include a file underneath an ignored
directory, this parser allows it. That is the escape hatch working as intended,
and it is only reachable from `.bishengignore`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# Content here is either wrong on the target machine (a host virtualenv, a
# platform-specific binary) or meaningless (VCS metadata, caches).
HARD_EXCLUDE_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".bisheng",
    }
)
HARD_EXCLUDE_PATTERNS = ("*.pyc", "*.egg-info/", ".DS_Store")

# Excluded by default, recoverable with a `!` line in .bishengignore.
SOFT_EXCLUDE_PATTERNS = (
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "dist/",
    "build/",
    "attachments/",
    "uploads/",
)

SUBSET_NOTICE = (
    "本项目不是 git 仓库（或本机没有 git），忽略规则按子集解析；"
    "复杂规则请写进 .bishengignore（同 .gitignore 语法，最后加载、优先级最高）。"
)

GITIGNORE_NAME = ".gitignore"
BISHENGIGNORE_NAME = ".bishengignore"


@dataclass
class _Rule:
    negate: bool
    dir_only: bool
    exact: re.Pattern[str]
    under: re.Pattern[str]

    def matches(self, path: str, is_dir: bool) -> bool:
        if self.under.match(path):
            return True
        if self.exact.match(path):
            return is_dir or not self.dir_only
        return False


@dataclass
class Ruleset:
    """An ordered `.gitignore`-style rule list. Last match wins."""

    rules: list[_Rule] = field(default_factory=list)

    @classmethod
    def parse(cls, text: str) -> Ruleset:
        rules = [rule for rule in (_compile(line) for line in text.splitlines()) if rule is not None]
        return cls(rules)

    @classmethod
    def from_file(cls, path: Path) -> Ruleset:
        if not path.is_file():
            return cls([])
        return cls.parse(path.read_text(encoding="utf-8", errors="replace"))

    def decide(self, path: str, is_dir: bool) -> bool | None:
        """True = ignored, False = explicitly taken back, None = no opinion."""
        verdict: bool | None = None
        for rule in self.rules:
            if rule.matches(path, is_dir):
                verdict = not rule.negate
        return verdict


def _compile(line: str) -> _Rule | None:
    raw = line.rstrip("\n")
    if not raw.strip() or raw.lstrip().startswith("#"):
        return None
    negate = raw.startswith("!")
    if negate:
        raw = raw[1:]
    raw = raw.strip()
    if not raw:
        return None
    dir_only = raw.endswith("/")
    raw = raw.rstrip("/")
    if not raw:
        return None
    anchored = raw.startswith("/") or "/" in raw
    raw = raw.lstrip("/")
    segments = raw.split("/")
    if segments and segments[-1] == "**":
        # `foo/**` means "everything under foo", which the `under` regex already
        # expresses; keeping the segment would demand a trailing slash that no
        # real path has.
        segments = segments[:-1]
    if not segments:
        return None
    body = _build_body(segments)
    if not anchored:
        body = "(?:[^/]+/)*" + body
    return _Rule(
        negate=negate,
        dir_only=dir_only,
        exact=re.compile("^" + body + "$"),
        under=re.compile("^" + body + "/.*$"),
    )


def _build_body(segments: list[str]) -> str:
    parts: list[str] = []
    for segment in segments:
        if segment == "**":
            parts.append("(?:[^/]+/)*")
            continue
        parts.append(_segment_regex(segment) + "/")
    body = "".join(parts)
    return body[:-1] if body.endswith("/") else body


def _segment_regex(segment: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(segment):
        ch = segment[index]
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        elif ch == "[":
            close = segment.find("]", index + 1)
            if close == -1:
                out.append(re.escape(ch))
            else:
                body = segment[index + 1 : close]
                body = body.replace("!", "^", 1) if body.startswith("!") else body
                out.append("[" + body + "]")
                index = close
        else:
            out.append(re.escape(ch))
        index += 1
    return "".join(out)


@dataclass
class IgnoreResult:
    files: list[str]
    excluded: list[str]
    used_git: bool
    notes: list[str]

    @property
    def excluded_count(self) -> int:
        return len(self.excluded)


def collect_files(root: Path, *, use_git: bool | None = None) -> IgnoreResult:
    """Decide the package contents for `root`."""
    root = Path(root)
    hard = Ruleset.parse("\n".join(HARD_EXCLUDE_PATTERNS))
    soft = Ruleset.parse("\n".join(SOFT_EXCLUDE_PATTERNS))
    bisheng = Ruleset.from_file(root / BISHENGIGNORE_NAME)
    notes: list[str] = []

    candidates, pruned = _walk(root)

    git_files = None
    if use_git is not False:
        git_files = _git_ls_files(root)
        if use_git is True and git_files is None:
            git_files = None
    used_git = git_files is not None
    if not used_git:
        gitignore = Ruleset.from_file(root / GITIGNORE_NAME)
        notes.append(SUBSET_NOTICE)
    else:
        gitignore = Ruleset([])

    included: list[str] = []
    excluded: list[str] = list(pruned)

    for rel, is_dir in candidates:
        if hard.decide(rel, is_dir) is True:
            excluded.append(rel)
            continue
        if used_git:
            keep = rel in git_files  # type: ignore[operator]
        else:
            keep = gitignore.decide(rel, is_dir) is not True
        if keep and soft.decide(rel, is_dir) is True:
            keep = False
        override = bisheng.decide(rel, is_dir)
        if override is True:
            keep = False
        elif override is False:
            keep = True
        (included if keep else excluded).append(rel)

    return IgnoreResult(files=sorted(included), excluded=sorted(excluded), used_git=used_git, notes=notes)


def _walk(root: Path) -> tuple[list[tuple[str, bool]], list[str]]:
    """List candidate entries, pruning hard-excluded directories as we go.

    Pruned directories are returned as a single entry each rather than expanded:
    walking a 400 MB `node_modules` only to throw every path away is the slowest
    possible way to reach the same answer.
    """
    candidates: list[tuple[str, bool]] = []
    pruned: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = PurePosixPath(Path(dirpath).relative_to(root).as_posix())
        keep_dirs = []
        for name in sorted(dirnames):
            rel = _join(rel_dir, name)
            if name in HARD_EXCLUDE_DIRS:
                pruned.append(rel + "/")
                continue
            if Path(dirpath, name).is_symlink():
                # Never descend through a link; record it so packaging can list
                # it as skipped instead of silently losing it.
                candidates.append((rel, True))
                continue
            keep_dirs.append(name)
        dirnames[:] = keep_dirs
        for name in sorted(filenames):
            candidates.append((_join(rel_dir, name), False))
    return candidates, pruned


def _join(rel_dir: PurePosixPath, name: str) -> str:
    text = str(rel_dir)
    return name if text == "." else f"{text}/{name}"


def _git_ls_files(root: Path) -> set[str] | None:
    """Ask git for the file list; None means "git could not answer"."""
    if not (root / ".git").exists() or shutil.which("git") is None:
        return None
    try:
        result = subprocess.run(
            ["git", "ls-files", "-c", "-o", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.decode("utf-8", errors="replace")
    return {entry for entry in raw.split("\0") if entry}
