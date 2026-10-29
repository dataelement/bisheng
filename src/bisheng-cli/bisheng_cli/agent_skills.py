"""Wire synced skill packs into the AI coding tools installed on this machine.

`skills sync` writes packs under `~/.bisheng/skills/`, which is the platform's own
directory — **no coding agent scans it**. A pack that lands there and stops there
is the worst failure this feature can produce: the agent keeps working, unaware of
the hosting contract, and the developer only finds out at `bisheng deploy`, from an
error that says nothing about a missing skill. Wrong-but-confident beats ignorant
here, and it beats it in the expensive direction. So syncing does not end at "files
written" — it wires the pack into every agent skills dir on the machine and reports
which ones took it.

Four rules this module pins down.

* **Install into all of them; never pick one.** Asymmetric cost: an extra link is
  a zero-byte inode, a missing one is a silent failure. And "which agent is the
  developer using right now" has no answer worth acting on — the same project gets
  opened in Codex today and Claude Code tomorrow, often both at once.
* **Link, don't copy.** A symlink means the next `sync` reaches every agent at
  once, and it keeps `~/.bisheng/skills/` the single source. Copying is the Windows
  fallback only (symlinks there need Developer Mode), and it is redone on every
  sync precisely because a copy cannot follow the source.
* **User-level, not project-level.** The pack's version follows the platform, not
  the project (see `commands/skills.py`), so it must not be committed into a
  business repo where git would freeze it at whatever the contract was that week.
  What belongs in the project is a *pointer* — `commands/deploy.py` writes that.
* **Never overwrite something we did not create.** A path already occupied by the
  developer's own skill is reported as a conflict and left alone. Managed copies
  carry a `.bisheng-managed` marker so a later sync can tell its own work from
  someone else's.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Coding tools that discover skills from a per-user directory. The home dir is the
# install signal (an agent may not have created `skills/` yet — it only appears
# once the user first has a skill), so detection keys off `~/.claude`, not
# `~/.claude/skills`.
#
# Tools without a skills-directory convention (Cursor, Cline, Windsurf, …) are not
# absent from the design — they read `AGENTS.md`, which is why `deploy` leaves a
# pointer there. Adding one of them *here* would create a directory the tool never
# reads, i.e. exactly the silent success this module exists to prevent.
KNOWN_AGENTS: tuple[tuple[str, str, str], ...] = (
    ("claude-code", "Claude Code", ".claude"),
    ("codex", "Codex", ".codex"),
)

SKILLS_SUBDIR = "skills"

# Written into a managed *copy* so a later sync knows it may replace it. Symlinks
# need no marker — their target already identifies them as ours.
MANAGED_MARKER = ".bisheng-managed"


@dataclass(frozen=True)
class AgentTarget:
    key: str
    label: str
    skills_dir: Path


def detect(home: Path | None = None) -> list[AgentTarget]:
    """Agent skills dirs on this machine, in `KNOWN_AGENTS` order."""
    root = home if home is not None else Path.home()
    found = []
    for key, label, dirname in KNOWN_AGENTS:
        agent_home = root / dirname
        if agent_home.is_dir():
            found.append(AgentTarget(key=key, label=label, skills_dir=agent_home / SKILLS_SUBDIR))
    return found


def install(pack_dir: Path, pack: str, targets: list[AgentTarget]) -> list[dict[str, Any]]:
    """Point every target at `pack_dir`. Never raises — a wiring failure is reported.

    One entry per target, with `status` in `linked` / `conflict` / `failed`. The
    caller decides how loud to be about each; this function only refuses to be the
    place where a failure disappears.
    """
    results: list[dict[str, Any]] = []
    for target in targets:
        results.append(_install_one(pack_dir, pack, target))
    return results


def _install_one(pack_dir: Path, pack: str, target: AgentTarget) -> dict[str, Any]:
    entry: dict[str, Any] = {"agent": target.key, "label": target.label, "pack": pack}
    link = target.skills_dir / pack
    entry["path"] = str(link)

    try:
        target.skills_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {**entry, "status": "failed", "reason": f"无法创建 {target.skills_dir}：{exc.__class__.__name__}"}

    occupied = _classify(link, pack_dir)
    if occupied == "foreign":
        return {
            **entry,
            "status": "conflict",
            "reason": f"{link} 已存在且不是本 CLI 创建的，未改动",
        }

    try:
        _clear(link)
    except OSError as exc:
        return {**entry, "status": "failed", "reason": f"无法清理 {link}：{exc.__class__.__name__}"}

    try:
        os.symlink(pack_dir, link, target_is_directory=True)
        return {**entry, "status": "linked", "mode": "symlink"}
    except (OSError, NotImplementedError, AttributeError):
        # Windows without Developer Mode, or a filesystem that has no symlinks.
        # A copy cannot follow later syncs, so it is re-made on every sync and the
        # mode is reported — the developer needs to know the link is not live.
        pass

    try:
        shutil.copytree(pack_dir, link)
        (link / MANAGED_MARKER).write_text("bisheng skills sync\n", encoding="utf-8")
        return {**entry, "status": "linked", "mode": "copy"}
    except OSError as exc:
        return {**entry, "status": "failed", "reason": f"无法写入 {link}：{exc.__class__.__name__}"}


def _classify(link: Path, pack_dir: Path) -> str:
    """`absent` / `managed` / `foreign` — who owns the path we want to occupy.

    A broken symlink counts as managed: it is the normal state after the user
    deletes `~/.bisheng`, and refusing to fix it would strand every agent.
    """
    if link.is_symlink():
        try:
            resolved = link.resolve()
        except OSError:
            return "managed"
        # Ours if it points into the bisheng skills tree at all — the profile slug
        # in between changes whenever the developer logs into another platform, so
        # matching the exact current target would wrongly call it foreign.
        bisheng_root = pack_dir.parent.parent
        return "managed" if (resolved == pack_dir or bisheng_root in resolved.parents) else "foreign"
    if not link.exists():
        return "absent"
    if link.is_dir() and (link / MANAGED_MARKER).is_file():
        return "managed"
    return "foreign"


def _clear(link: Path) -> None:
    if link.is_symlink() or link.is_file():
        link.unlink()
    elif link.is_dir():
        shutil.rmtree(link)


def summarise(results: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    """`(labels that took the pack, entries that did not)`."""
    linked = [r["label"] for r in results if r.get("status") == "linked"]
    problems = [r for r in results if r.get("status") != "linked"]
    return linked, problems


# ---- project-level pointer ----------------------------------------------

POINTER_FILE = "AGENTS.md"
POINTER_MARKER = "<!-- bisheng-skills -->"


def ensure_project_pointer(root: Path, skills_root: Path, packs: list[str]) -> dict[str, Any]:
    """Leave a pointer to the packs in the project's ``AGENTS.md``.

    A *pointer*, never the pack itself. The pack's version follows the platform, so
    a copy committed to a business repo is frozen at whatever the contract was that
    week and goes on being read long after it stopped being true. A path does not
    rot the same way, and it is the only channel that reaches tools with no skills
    directory at all (Cursor, Cline, Windsurf).

    Written with ``~`` rather than the absolute home path on purpose: this file is
    meant to be committed, and a teammate's home dir is not the developer's. The
    profile slug is derived from the platform URL, so it is the same for everyone
    deploying to the same platform.

    Idempotent via `POINTER_MARKER`, and strictly additive — an existing AGENTS.md
    is appended to, never rewritten.
    """
    path = Path(root) / POINTER_FILE
    try:
        existing = path.read_text(encoding="utf-8") if path.is_file() else None
    except OSError as exc:
        return {"status": "failed", "path": str(path), "reason": exc.__class__.__name__}

    if existing is not None and POINTER_MARKER in existing:
        return {"status": "present", "path": str(path)}

    block = _pointer_block(skills_root, packs)
    try:
        if existing is None:
            path.write_text(block, encoding="utf-8")
            return {"status": "created", "path": str(path)}
        separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
        path.write_text(existing + separator + block, encoding="utf-8")
        return {"status": "appended", "path": str(path)}
    except OSError as exc:
        return {"status": "failed", "path": str(path), "reason": exc.__class__.__name__}


def _display_root(skills_root: Path) -> str:
    """`~/.bisheng/skills/<slug>` — home-relative so the line survives being committed."""
    try:
        return "~/" + str(Path(skills_root).relative_to(Path.home()))
    except ValueError:
        return str(skills_root)


def _pointer_block(skills_root: Path, packs: list[str]) -> str:
    root = _display_root(skills_root)
    lines = [
        POINTER_MARKER,
        "## BiSheng 应用平台",
        "",
        "本项目通过 `bisheng deploy` 部署到 BiSheng 应用平台。托管契约（应用必须遵守的约定）、",
        "`bisheng-app.yaml` 的写法和部署排障都在技能包里，改动本项目前请先读：",
        "",
    ]
    lines += [f"- `{root}/{pack}/SKILL.md`" for pack in packs]
    lines += [
        "",
        "技能包由 `bisheng skills sync` 获取、版本跟随平台，不要拷贝进本仓库——拷贝会被 git",
        "冻结在旧版本，而平台的规矩会继续变。",
        "",
    ]
    return "\n".join(lines)
