"""T015 — the three ignore layers.

The load-bearing test here is the first one: git and the hand-written subset
parser must agree on the same tree. When they diverge, nothing fails — the
package silently contains (or omits) different files depending on whether the
developer happened to have git installed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bisheng_cli.ignore import ALL_IGNORED_NOTICE, SUBSET_NOTICE, Ruleset, collect_files


def _names(root: Path, **kw) -> set[str]:
    return set(collect_files(root, **kw).files)


def test_git_path_and_subset_parser_agree_on_sample_tree(sample_project_git: Path) -> None:
    via_git = collect_files(sample_project_git, use_git=True)
    via_subset = collect_files(sample_project_git, use_git=False)
    assert via_git.used_git is True and via_subset.used_git is False
    assert set(via_git.files) == set(via_subset.files)


def test_gitignore_rules_are_honoured(sample_project: Path) -> None:
    files = _names(sample_project, use_git=False)
    assert "debug.log" not in files
    assert "build-artifacts/old.tar" not in files
    assert "important.log" in files  # taken back by the ! rule


def test_double_star_matches_across_directories() -> None:
    rules = Ruleset.parse("logs/**/*.tmp\n")
    assert rules.decide("logs/a.tmp", False) is True
    assert rules.decide("logs/x/y/a.tmp", False) is True
    assert rules.decide("other/a.tmp", False) is None


def test_single_star_does_not_cross_slash() -> None:
    # fnmatch's `*` crosses `/` and it has no `**` at all — using it directly is
    # how a rule silently matches nothing (or everything).
    rules = Ruleset.parse("a/*.log\n")
    assert rules.decide("a/b.log", False) is True
    assert rules.decide("a/x/b.log", False) is None


def test_leading_bang_negation_takes_back() -> None:
    rules = Ruleset.parse("*.log\n!keep.log\n")
    assert rules.decide("debug.log", False) is True
    assert rules.decide("keep.log", False) is False


def test_trailing_slash_matches_directory_only() -> None:
    rules = Ruleset.parse("cache/\n")
    assert rules.decide("cache", True) is True
    assert rules.decide("cache/x.txt", False) is True
    assert rules.decide("cache", False) is None  # a *file* named cache is untouched


def test_comments_and_blank_lines_are_skipped() -> None:
    rules = Ruleset.parse("# comment\n\n   \n*.log\n")
    assert len(rules.rules) == 1


def test_bishengignore_loaded_last_and_wins(sample_project: Path) -> None:
    (sample_project / ".bishengignore").write_text("!debug.log\nmain.py\n", encoding="utf-8")
    files = _names(sample_project, use_git=False)
    assert "debug.log" in files  # taken back from .gitignore
    assert "main.py" not in files  # newly excluded


def test_hard_excluded_dirs_cannot_be_taken_back_by_bang(sample_project: Path) -> None:
    (sample_project / ".bishengignore").write_text("!.venv/**\n!node_modules/**\n!.bisheng/**\n", encoding="utf-8")
    files = _names(sample_project, use_git=False)
    assert not [f for f in files if f.startswith((".venv/", "node_modules/", "__pycache__/", ".bisheng/"))]


def test_dist_and_build_are_soft_excluded_and_can_be_taken_back(sample_project: Path) -> None:
    # dist/ deliberately is NOT a hard exclude: plenty of real apps ship a
    # front-end bundle there for the backend to serve statically, and hard-excluding
    # it strips the app silently — the failure only shows up at probe time, pointing
    # the investigation at "the platform build is broken".
    assert "dist/bundle.js" not in _names(sample_project, use_git=False)
    (sample_project / ".bishengignore").write_text("!dist/**\n", encoding="utf-8")
    assert "dist/bundle.js" in _names(sample_project, use_git=False)


def test_local_sqlite_is_soft_excluded(sample_project: Path) -> None:
    assert "app.sqlite" not in _names(sample_project, use_git=False)


def test_non_git_project_output_says_subset_parsing_used(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    (root / "main.py").write_text("x\n", encoding="utf-8")
    result = collect_files(root)
    assert result.used_git is False
    assert any("子集解析" in note and ".bishengignore" in note for note in result.notes)


def test_git_project_does_not_emit_the_subset_notice(sample_project_git: Path) -> None:
    result = collect_files(sample_project_git)
    assert result.used_git is True
    assert not [note for note in result.notes if "子集解析" in note]


def test_excluded_entries_are_reported_not_silently_dropped(sample_project: Path) -> None:
    result = collect_files(sample_project, use_git=False)
    assert result.excluded_count > 0
    assert any(entry.startswith(".venv") for entry in result.excluded)


@pytest.mark.parametrize("pattern", ["**", "", "   ", "#only a comment"])
def test_degenerate_patterns_do_not_crash(pattern: str) -> None:
    Ruleset.parse(pattern + "\n").decide("a/b.txt", False)


def test_app_directory_inside_a_repo_uses_git_not_the_subset_parser(tmp_path: Path) -> None:
    """An app folder inside a larger repo is the common case, not the exotic one.

    Gating on ``root/".git"`` made this directory report "not a git repository"
    and fall back to reading only its own ``.gitignore`` — while the repo's real
    rules sit at the repo root. Anything git ignores from above (local data,
    generated output, an ignored config with real credentials in it) would then
    be packed and uploaded.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("secrets.env\n*.local\n")
    app = tmp_path / "examples" / "demo"
    app.mkdir(parents=True)
    (app / "main.py").write_text("print('hi')\n")
    (app / "secrets.env").write_text("TOKEN=real\n")
    (app / "notes.local").write_text("scratch\n")

    result = collect_files(app)

    assert result.used_git is True, "the parent repo must be found from a subdirectory"
    assert "main.py" in result.files
    assert "secrets.env" not in result.files, "an ignore rule from the repo root must still apply"
    assert "notes.local" not in result.files
    assert SUBSET_NOTICE not in result.notes


def test_fully_ignored_directory_says_so_instead_of_packing_nothing_silently(tmp_path: Path) -> None:
    """"git ignores everything here" and "there is nothing here" need different fixes.

    Without the note, the only symptom is a later "bisheng-app.yaml missing"
    error, which points at the manifest rather than at the ignore rule that
    swallowed the whole directory.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("vendor/\n")
    app = tmp_path / "vendor" / "app"
    app.mkdir(parents=True)
    (app / "main.py").write_text("print('hi')\n")
    (app / "bisheng-app.yaml").write_text("name: x\n")

    result = collect_files(app)

    assert result.files == []
    assert ALL_IGNORED_NOTICE in result.notes
