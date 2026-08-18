"""`bisheng skills sync` — pull the platform's developer skill packs to this machine.

A skill pack is guidance an AI coding tool reads so it builds an app that fits the
platform's hosting contract. The platform ships exactly one copy of each pack
(AC-15, 内外同源); ``sync`` fetches that copy from the anonymous distribution
endpoint into ``~/.bisheng/skills/`` so any local agent can reference it.

Two rules the design pins down (决议-8, AC-21):

* **One-way overwrite.** The pack is a platform release artifact, not the
  developer's file. ``sync`` replaces the local copy wholesale — no three-way
  merge, no keep-my-edits, no confirm-before-overwrite — and lists what it
  overwrote so a developer who had edited a pack file is told, not surprised.
  Local customisation belongs in the project's own ``AGENTS.md``, outside the
  pack dir.
* **Version follows the platform.** There is no pack version to pick; whatever
  platform you are logged into decides it, and re-running after a platform
  upgrade is how you update.

The pack ships next to the CLI wheel behind the same anonymous, conditionally
registered router, so a 404 here means the same thing it means for the wheel: the
open-capability layer is not on (or the platform predates skill packs). The
command reports that as its own exit code rather than as a mysterious empty sync.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import Any

from bisheng_cli import credentials
from bisheng_cli.errors import EXIT_LOCAL_INVALID, EXIT_NOT_ENABLED, EXIT_OK, EXIT_USAGE, CliError
from bisheng_cli.http import PlatformClient
from bisheng_cli.output import Emitter

COMMAND = "skills"

#: Packs the platform ships. Only「部署纳管」this round;「平台能力接线」lands with
#: F057. A pack the platform does not carry answers 404 and is reported as such,
#: so listing it here early is harmless — but it is not, until it exists.
DEFAULT_PACKS: tuple[str, ...] = ("deploy-hosting",)

SKILLS_ENDPOINT = "/api/v1/dev-toolkit/skills/{pack}"
# Header the endpoint stamps with the platform version the pack shipped with.
PACK_VERSION_HEADER = "x-bisheng-pack-version"

# Where packs land: a sibling of credentials.json under ~/.bisheng, so the whole
# developer state lives in one 0700 directory.
SKILLS_DIR_NAME = "skills"


def _skills_root() -> Path:
    return credentials.credentials_path().parent / SKILLS_DIR_NAME


def run(args: Any, emitter: Emitter) -> int:
    """Entry point. Only ``sync`` exists today; a bare ``skills`` prints usage."""
    sub = getattr(args, "skills_command", None)
    if sub != "sync":
        emitter.error("用法: bisheng skills sync")
        emitter.error("将平台当前版本的开发者技能包同步到本地用户目录（~/.bisheng/skills/）。")
        return EXIT_USAGE

    profile = credentials.load_current()
    client = PlatformClient(
        profile.base_url,
        api_key=profile.api_key,
        trust_env=not getattr(args, "no_proxy", False),
        timeout=getattr(args, "timeout", None),
        emitter=emitter,
    )
    with client:
        packs = sync_packs(client, emitter)

    _print_reference_guide(emitter)
    emitter.result(COMMAND, ok=True, exit_code=EXIT_OK, data={"skills_dir": str(_skills_root()), "packs": packs})
    return EXIT_OK


def run_after_login(profile: credentials.Profile, args: Any, emitter: Emitter) -> None:
    """Best-effort sync triggered by a successful ``login`` (AC-08).

    Login has already succeeded and its own ``result`` event is what the command
    reports, so this must never raise and must never emit a ``result`` — a
    failure here downgrades to a warning that tells the developer to re-run
    ``skills sync`` by hand. Same reason it does not print the reference guide:
    the login output already ended.
    """
    try:
        client = PlatformClient(
            profile.base_url,
            api_key=profile.api_key,
            trust_env=not getattr(args, "no_proxy", False),
            timeout=getattr(args, "timeout", None),
            emitter=emitter,
        )
        with client:
            sync_packs(client, emitter)
    except CliError as exc:
        emitter.warn(f"技能包自动同步未完成：{exc.message}")
        emitter.info("  可稍后手动执行 bisheng skills sync 重试。")
    except Exception as exc:
        emitter.warn(f"技能包自动同步未完成：{exc.__class__.__name__}")
        emitter.info("  可稍后手动执行 bisheng skills sync 重试。")


def sync_packs(client: PlatformClient, emitter: Emitter) -> list[dict[str, Any]]:
    """Fetch and unpack each shipped pack. Prints one line per pack; may raise."""
    root = _skills_root()
    results: list[dict[str, Any]] = []
    for pack in DEFAULT_PACKS:
        results.append(_sync_one(client, pack, root, emitter))
    return results


def _sync_one(client: PlatformClient, pack: str, root: Path, emitter: Emitter) -> dict[str, Any]:
    resp = client.request("GET", SKILLS_ENDPOINT.format(pack=pack))
    if resp.status_code == 404:
        # The whole dev-toolkit router is absent when the open layer is off, so a
        # missing wheel and a missing pack both surface here as 404. Either way
        # the developer's next move is the platform admin, not their own machine.
        raise CliError(
            f"平台未提供技能包 {pack}",
            exit_code=EXIT_NOT_ENABLED,
            next_step="确认平台已启用开放能力层（open_platform）并升级到含技能包的版本，再重试。",
        )
    if resp.status_code >= 400:
        raise CliError(
            f"拉取技能包 {pack} 失败（HTTP {resp.status_code}）",
            exit_code=EXIT_NOT_ENABLED,
            next_step="稍后重试；持续失败请联系平台管理员。",
        )

    version = resp.headers.get(PACK_VERSION_HEADER)
    written, overwritten = _extract(resp.content, root, pack)

    label = f"版本 {version}" if version else "平台当前版本"
    emitter.info(
        f"✓ {pack}（{label}）：{len(written)} 个文件已同步" + (f"，覆盖 {len(overwritten)} 个" if overwritten else "")
    )
    for name in overwritten:
        emitter.debug(f"  覆盖 {name}")
    return {"pack": pack, "version": version, "files": written, "overwritten": overwritten}


def _extract(content: bytes, root: Path, pack: str) -> tuple[list[str], list[str]]:
    """Unpack ``pack.tar.gz`` into ``root/pack``, overwriting wholesale.

    Returns ``(files_written, files_overwritten)`` — both relative to ``root`` so
    they read as ``deploy-hosting/SKILL.md``. Overwritten = files that existed
    before this sync, which is the set AC-21 wants surfaced.
    """
    pack_dir = root / pack
    prior = _existing_files(pack_dir, root)

    try:
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
            members = _safe_members(tar, root, pack)
            # One-way overwrite: drop the old tree entirely, then lay down the
            # platform version. No merge means no half-updated pack.
            _rmtree(pack_dir)
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            tar.extractall(path=root, members=members)
            written = sorted(m.name for m in members if m.isfile())
    except (tarfile.TarError, OSError) as exc:
        raise CliError(
            f"技能包 {pack} 解包失败：{exc.__class__.__name__}",
            exit_code=EXIT_LOCAL_INVALID,
            next_step="删除后重试，或联系平台管理员确认发布件完整。",
        )

    overwritten = sorted(prior & set(written))
    return written, overwritten


def _safe_members(tar: tarfile.TarFile, root: Path, pack: str) -> list[tarfile.TarInfo]:
    """Members guaranteed to unpack inside ``root/pack`` — nothing else is trusted.

    The tarball comes from the platform the developer logged into, but a path
    that climbs out of the pack dir is never legitimate, so it is rejected rather
    than sanitised. Every member must live under the ``pack/`` arcname the
    endpoint writes.
    """
    root_resolved = root.resolve()
    pack_prefix = f"{pack}/"
    safe: list[tarfile.TarInfo] = []
    for member in tar.getmembers():
        name = member.name
        if member.islnk() or member.issym():
            raise CliError(
                f"技能包含有链接条目（{name}），拒绝解包",
                exit_code=EXIT_LOCAL_INVALID,
                next_step="联系平台管理员确认发布件未被篡改。",
            )
        if name != pack and not name.startswith(pack_prefix):
            raise CliError(
                f"技能包含有越界条目（{name}），拒绝解包",
                exit_code=EXIT_LOCAL_INVALID,
                next_step="联系平台管理员确认发布件未被篡改。",
            )
        target = (root / name).resolve()
        if target != root_resolved / pack and root_resolved / pack not in target.parents:
            raise CliError(
                f"技能包条目路径越界（{name}），拒绝解包",
                exit_code=EXIT_LOCAL_INVALID,
                next_step="联系平台管理员确认发布件未被篡改。",
            )
        safe.append(member)
    return safe


def _existing_files(pack_dir: Path, root: Path) -> set[str]:
    if not pack_dir.exists():
        return set()
    return {str(p.relative_to(root)) for p in pack_dir.rglob("*") if p.is_file()}


def _rmtree(path: Path) -> None:
    """Remove a directory tree without importing shutil for one call site."""
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()


def _print_reference_guide(emitter: Emitter) -> None:
    """After sync, tell the developer how to point their AI tool at the packs (AC-20)."""
    root = _skills_root()
    emitter.info("")
    emitter.info(f"技能包已同步到 {root}")
    emitter.info("  · Claude Code：自动发现 SKILL.md，无需配置。")
    emitter.info(f"  · 其它 AI 编程工具：在项目里放一个 AGENTS.md 指向 {root}/<包名>/SKILL.md。")
    emitter.info(f"  · 详见 {root}/README.md。")
