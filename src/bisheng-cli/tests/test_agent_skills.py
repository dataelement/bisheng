"""Wiring synced packs into the AI coding tools on the machine.

The bug this module answers looked like a success: `login` printed
"5 个文件已同步", the files really were on disk under `~/.bisheng/skills/`, and
nothing on the machine could read them — no agent scans that directory. So the
tests here are mostly about the *reporting* contract as much as the linking one:
a pack that reaches no agent must be loud, and a path the CLI did not create must
never be overwritten to make the summary look better.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bisheng_cli import agent_skills


def _pack(home: Path, *, slug: str = "platform.test.abcd1234", pack: str = "deploy-hosting") -> Path:
    """A synced pack in its real shape: ~/.bisheng/skills/<slug>/<pack>/."""
    pack_dir = home / ".bisheng" / "skills" / slug / pack
    (pack_dir / "example").mkdir(parents=True)
    (pack_dir / "SKILL.md").write_text("# deploy-hosting\n", encoding="utf-8")
    (pack_dir / "example" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    return pack_dir


# ---- detection ------------------------------------------------------------


def test_detects_nothing_on_a_bare_machine(home_dir: Path) -> None:
    assert agent_skills.detect() == []


def test_detects_both_agents_and_keeps_them_both(home_dir: Path) -> None:
    # The whole point: with two tools installed we install into two, never pick.
    (home_dir / ".claude").mkdir()
    (home_dir / ".codex").mkdir()
    assert [t.key for t in agent_skills.detect()] == ["claude-code", "codex"]


def test_detects_agent_whose_skills_dir_does_not_exist_yet(home_dir: Path) -> None:
    # `~/.claude/skills` only appears once the user has a skill; keying detection
    # off it would skip exactly the first-time developer this feature is for.
    (home_dir / ".claude").mkdir()
    targets = agent_skills.detect()
    assert len(targets) == 1
    assert not targets[0].skills_dir.exists()


# ---- installing -----------------------------------------------------------


def test_installs_into_every_detected_agent(home_dir: Path) -> None:
    (home_dir / ".claude").mkdir()
    (home_dir / ".codex").mkdir()
    pack_dir = _pack(home_dir)

    results = agent_skills.install(pack_dir, "deploy-hosting", agent_skills.detect())

    assert [r["status"] for r in results] == ["linked", "linked"]
    for agent in (".claude", ".codex"):
        link = home_dir / agent / "skills" / "deploy-hosting"
        assert link.is_symlink()
        assert (link / "SKILL.md").read_text(encoding="utf-8") == "# deploy-hosting\n"


def test_install_is_idempotent(home_dir: Path) -> None:
    (home_dir / ".claude").mkdir()
    pack_dir = _pack(home_dir)
    agent_skills.install(pack_dir, "deploy-hosting", agent_skills.detect())
    results = agent_skills.install(pack_dir, "deploy-hosting", agent_skills.detect())
    assert results[0]["status"] == "linked"
    assert (home_dir / ".claude" / "skills" / "deploy-hosting" / "SKILL.md").is_file()


def test_relinks_when_the_platform_changes(home_dir: Path) -> None:
    """Logging into another platform must repoint the link, not report a conflict.

    The link from the previous platform is ours — same tree, different slug — so
    it gets replaced. Treating it as foreign would leave every agent reading the
    old platform's contract with nothing on screen to say so.
    """
    (home_dir / ".claude").mkdir()
    first = _pack(home_dir, slug="old.platform.11111111")
    agent_skills.install(first, "deploy-hosting", agent_skills.detect())

    second = _pack(home_dir, slug="new.platform.22222222")
    (second / "SKILL.md").write_text("# new platform\n", encoding="utf-8")
    results = agent_skills.install(second, "deploy-hosting", agent_skills.detect())

    assert results[0]["status"] == "linked"
    link = home_dir / ".claude" / "skills" / "deploy-hosting"
    assert link.resolve() == second.resolve()
    assert (link / "SKILL.md").read_text(encoding="utf-8") == "# new platform\n"


def test_repairs_a_broken_link(home_dir: Path) -> None:
    # Normal state after someone deletes ~/.bisheng. Leaving it dangling would
    # strand the agent on a path that resolves to nothing.
    (home_dir / ".claude" / "skills").mkdir(parents=True)
    link = home_dir / ".claude" / "skills" / "deploy-hosting"
    os.symlink(home_dir / ".bisheng" / "skills" / "gone" / "deploy-hosting", link)
    pack_dir = _pack(home_dir)

    results = agent_skills.install(pack_dir, "deploy-hosting", agent_skills.detect())

    assert results[0]["status"] == "linked"
    assert (link / "SKILL.md").is_file()


def test_never_overwrites_a_skill_the_developer_owns(home_dir: Path) -> None:
    """A real directory at the target path is the developer's, and stays untouched.

    Deleting it would make the summary read "已接入" at the cost of destroying
    someone's own skill — the one outcome worse than not installing at all.
    """
    (home_dir / ".claude" / "skills" / "deploy-hosting").mkdir(parents=True)
    mine = home_dir / ".claude" / "skills" / "deploy-hosting" / "SKILL.md"
    mine.write_text("我自己写的\n", encoding="utf-8")
    pack_dir = _pack(home_dir)

    results = agent_skills.install(pack_dir, "deploy-hosting", agent_skills.detect())

    assert results[0]["status"] == "conflict"
    assert mine.read_text(encoding="utf-8") == "我自己写的\n"


def test_foreign_symlink_is_a_conflict_too(home_dir: Path) -> None:
    (home_dir / ".claude" / "skills").mkdir(parents=True)
    elsewhere = home_dir / "my-skills" / "deploy-hosting"
    elsewhere.mkdir(parents=True)
    os.symlink(elsewhere, home_dir / ".claude" / "skills" / "deploy-hosting")
    pack_dir = _pack(home_dir)

    results = agent_skills.install(pack_dir, "deploy-hosting", agent_skills.detect())

    assert results[0]["status"] == "conflict"
    assert (home_dir / ".claude" / "skills" / "deploy-hosting").resolve() == elsewhere.resolve()


def test_falls_back_to_copy_when_symlinks_are_unavailable(home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows without Developer Mode. A copy cannot follow later syncs, so the
    # mode is reported rather than smoothed over.
    (home_dir / ".claude").mkdir()
    pack_dir = _pack(home_dir)
    monkeypatch.setattr(agent_skills.os, "symlink", _raise_oserror)

    results = agent_skills.install(pack_dir, "deploy-hosting", agent_skills.detect())

    assert results[0]["status"] == "linked"
    assert results[0]["mode"] == "copy"
    link = home_dir / ".claude" / "skills" / "deploy-hosting"
    assert not link.is_symlink()
    assert (link / "SKILL.md").is_file()
    assert (link / agent_skills.MANAGED_MARKER).is_file()


def test_a_managed_copy_is_replaceable_but_a_plain_dir_is_not(home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (home_dir / ".claude").mkdir()
    pack_dir = _pack(home_dir)
    monkeypatch.setattr(agent_skills.os, "symlink", _raise_oserror)
    agent_skills.install(pack_dir, "deploy-hosting", agent_skills.detect())

    (pack_dir / "SKILL.md").write_text("# v2\n", encoding="utf-8")
    results = agent_skills.install(pack_dir, "deploy-hosting", agent_skills.detect())

    assert results[0]["status"] == "linked"
    link = home_dir / ".claude" / "skills" / "deploy-hosting"
    assert (link / "SKILL.md").read_text(encoding="utf-8") == "# v2\n"


def _raise_oserror(*_args: object, **_kwargs: object) -> None:
    raise OSError("symlink unsupported")


# ---- summarise ------------------------------------------------------------


def test_summarise_splits_linked_from_problems() -> None:
    linked, problems = agent_skills.summarise(
        [
            {"label": "Claude Code", "status": "linked"},
            {"label": "Codex", "status": "conflict", "reason": "占用"},
        ]
    )
    assert linked == ["Claude Code"]
    assert [p["label"] for p in problems] == ["Codex"]


# ---- project pointer ------------------------------------------------------


def test_pointer_created_when_agents_md_absent(home_dir: Path, tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    skills_root = home_dir / ".bisheng" / "skills" / "platform.test.abcd1234"

    outcome = agent_skills.ensure_project_pointer(project, skills_root, ["deploy-hosting"])

    assert outcome["status"] == "created"
    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert agent_skills.POINTER_MARKER in text
    assert "deploy-hosting/SKILL.md" in text
    # Home-relative, because this file gets committed and a teammate's home differs.
    assert str(home_dir) not in text
    assert "~/.bisheng/skills/platform.test.abcd1234" in text


def test_pointer_appends_and_never_rewrites(home_dir: Path, tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    existing = "# 我的项目\n\n本地约定若干。\n"
    (project / "AGENTS.md").write_text(existing, encoding="utf-8")

    outcome = agent_skills.ensure_project_pointer(project, home_dir / ".bisheng" / "skills" / "s", ["deploy-hosting"])

    assert outcome["status"] == "appended"
    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert text.startswith(existing)
    assert agent_skills.POINTER_MARKER in text


def test_pointer_is_idempotent(home_dir: Path, tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    skills_root = home_dir / ".bisheng" / "skills" / "s"
    agent_skills.ensure_project_pointer(project, skills_root, ["deploy-hosting"])
    first = (project / "AGENTS.md").read_text(encoding="utf-8")

    outcome = agent_skills.ensure_project_pointer(project, skills_root, ["deploy-hosting"])

    assert outcome["status"] == "present"
    assert (project / "AGENTS.md").read_text(encoding="utf-8") == first


def test_pointer_failure_is_reported_not_raised(home_dir: Path, tmp_path: Path) -> None:
    # A directory named AGENTS.md: unreadable and unwritable as a file. Deploy
    # must survive it, so the failure comes back as data.
    project = tmp_path / "proj"
    (project / "AGENTS.md").mkdir(parents=True)

    outcome = agent_skills.ensure_project_pointer(project, home_dir / ".bisheng" / "skills" / "s", ["deploy-hosting"])

    assert outcome["status"] == "failed"
