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

Two things sync does beyond unpacking, both of them corrections to a version that
merely wrote files and called it success:

* **Packs are stored per platform.** ``~/.bisheng/skills/<platform>/<pack>/``. One
  machine logging into a test platform and a production one used to have the
  second login silently overwrite the first's contract, leaving the developer's
  agent reading the wrong platform's rules with nothing on screen to suggest it.
* **Sync wires the pack into the local agents.** Writing into ``~/.bisheng`` alone
  reaches nobody — see ``agent_skills`` for why an unwired pack is the expensive
  failure mode and why every detected agent gets one.
"""

from __future__ import annotations

import hashlib
import io
import re
import tarfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bisheng_cli import agent_skills, credentials
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


def _skills_base() -> Path:
    return credentials.credentials_path().parent / SKILLS_DIR_NAME


def profile_slug(base_url: str) -> str:
    """Directory name for one platform's packs: readable host + disambiguating hash.

    The host alone is not enough (`http://x` and `https://x` are two platforms with
    two contracts), and a bare hash is unreadable in the path line the CLI prints. So
    both: the netloc for a human, eight hex for uniqueness. Derived from the
    normalised URL, i.e. the same key the credential store profiles by — anything
    else would let two spellings of one platform own two pack copies.
    """
    key = credentials.normalise_base_url(base_url)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    readable = re.sub(r"[^a-z0-9.-]+", "-", (urlsplit(key).netloc or "platform").lower()).strip("-")
    return f"{readable or 'platform'}.{digest}"


def skills_root(base_url: str) -> Path:
    """Where this platform's packs live. Public: `deploy` cites it in AGENTS.md."""
    return _skills_base() / profile_slug(base_url)


# Internal call sites kept short; same function, one implementation.
_skills_root = skills_root


def _migrate_flat_layout(emitter: Emitter) -> None:
    """Drop pre-profile packs sitting directly under ``~/.bisheng/skills/``.

    Only ever removes a directory whose name is a pack we ship — a slug always
    carries a ``.`` + hash, so the two namespaces cannot collide. Left in place the
    old copy is a decoy: nothing updates it, and a developer who finds it has no
    way to tell it from the live one.
    """
    base = _skills_base()
    for pack in DEFAULT_PACKS:
        stale = base / pack
        if stale.is_dir() and not stale.is_symlink():
            try:
                _rmtree(stale)
                emitter.debug(f"已清理旧版落点 {stale}")
            except OSError:
                emitter.debug(f"旧版落点 {stale} 清理失败，可手动删除")


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
        packs = sync_packs(client, profile.base_url, emitter)

    _print_reference_guide(profile.base_url, packs, emitter)
    emitter.result(
        COMMAND,
        ok=True,
        exit_code=EXIT_OK,
        data={"skills_dir": str(_skills_root(profile.base_url)), "packs": packs},
    )
    return EXIT_OK


def run_after_login(profile: credentials.Profile, args: Any, emitter: Emitter) -> None:
    """Best-effort sync triggered by a successful ``login`` (AC-08).

    Login has already succeeded and its own ``result`` event is what the command
    reports, so this must never raise and must never emit a ``result`` — a
    failure here downgrades to a warning that tells the developer to re-run
    ``skills sync`` by hand.

    It *does* print where the pack went and which agents took it. The earlier
    version stayed silent to keep the login output short, and that silence was the
    whole bug this round fixes: "5 个文件已同步" told the developer a sync had
    happened while leaving them no way to learn that nothing could read it.
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
            packs = sync_packs(client, profile.base_url, emitter)
        _print_reference_guide(profile.base_url, packs, emitter)
    except CliError as exc:
        emitter.warn(f"技能包自动同步未完成：{exc.message}")
        emitter.info("  可稍后手动执行 bisheng skills sync 重试。")
    except Exception as exc:
        emitter.warn(f"技能包自动同步未完成：{exc.__class__.__name__}")
        emitter.info("  可稍后手动执行 bisheng skills sync 重试。")


def sync_packs(client: PlatformClient, base_url: str, emitter: Emitter) -> list[dict[str, Any]]:
    """Fetch, unpack and wire each shipped pack. One line per pack; may raise."""
    root = _skills_root(base_url)
    targets = agent_skills.detect()
    results: list[dict[str, Any]] = []
    for pack in DEFAULT_PACKS:
        result = _sync_one(client, pack, root, emitter)
        # Wiring runs per pack and after its files are on disk, so a pack that
        # failed to download never gets linked to a half-written directory.
        result["agents"] = agent_skills.install(root / pack, pack, targets)
        _report_agents(result, emitter)
        results.append(result)
    _migrate_flat_layout(emitter)
    return results


def _report_agents(result: dict[str, Any], emitter: Emitter) -> None:
    """Say which agents took the pack — and be loud when none did.

    "No agent found" is not a footnote: it means the sync that just reported
    success cannot affect anything the developer's AI does.
    """
    linked, problems = agent_skills.summarise(result.get("agents") or [])
    if linked:
        emitter.info(f"  已接入 {'、'.join(linked)}")
    else:
        emitter.warn("技能包已下载，但本机未接入任何 AI 编程工具——AI 读不到平台规矩。")
    for problem in problems:
        emitter.warn(f"{problem.get('label')} 未接入：{problem.get('reason') or problem.get('status')}")


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


def _print_reference_guide(base_url: str, packs: list[dict[str, Any]], emitter: Emitter) -> None:
    """After sync, say where the packs went and how anything else reaches them (AC-20).

    The previous wording claimed "Claude Code：自动发现 SKILL.md，无需配置" and pointed
    at a ``README.md`` the pack does not contain. Both were wrong in the same
    direction — they told the developer there was nothing left to do. No agent
    scans ``~/.bisheng/skills/``; that is what ``agent_skills`` exists to fix, and
    what this guide now reports instead of promising.
    """
    root = _skills_root(base_url)
    linked = sorted({r["label"] for pack in packs for r in (pack.get("agents") or []) if r.get("status") == "linked"})
    emitter.info("")
    emitter.info(f"技能包落点：{root}（按平台分目录，切换平台不会互相覆盖）")
    if linked:
        emitter.info(f"  · 已自动接入：{'、'.join(linked)}——新开一个会话即可生效。")
    else:
        emitter.info("  · 本机未发现 Claude Code / Codex；技能包只是下载了，还没有任何工具能读到。")
    emitter.info("  · 其它 AI 编程工具（Cursor、Cline 等）：在项目 AGENTS.md 里指向")
    emitter.info(f"    {root}/<包名>/SKILL.md；bisheng deploy 会自动写好这一行。")
