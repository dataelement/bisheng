"""Build the version snapshot: a reproducible tar.gz, or a refusal with a report.

Four rules, each the dual of a real failure.

**Never truncate silently.** Over the limit means the whole package is refused
and the offenders are listed. A package quietly trimmed to fit means what runs in
production is not what the developer has locally, and nothing anywhere says so.

**Skip links and special files locally, and say which.** The server's unpack gate
rejects symlinks, hardlinks, device nodes and FIFOs. Not skipping them here buys
a 16202 *after* the upload; skipping them without listing them buys a missing file
nobody can account for.

**Reproducible bytes.** Members sorted, mtime zeroed, uid/gid/uname/gname cleared,
gzip header stripped of its timestamp. Same content, same sha256 — which is what
makes "the package I built is the package the server received" checkable at all.

**Keep the owner execute bit.** Normalising every mode to 0644 leaves the
entrypoint script non-executable, and that failure only appears at build or probe
time, pointing the investigation at the platform instead of at the tarball.

tar.gz, not zip: F055's endpoint parameter is literally `package` and its object
key ends in `code.tar.gz`. Producing a zip would be wrong against the wording,
the object key, and any future chunked-upload scheme at once, in exchange for
nothing.
"""

from __future__ import annotations

import gzip
import hashlib
import stat as stat_module
import tarfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from bisheng_cli.errors import EXIT_LOCAL_INVALID, CliError
from bisheng_cli.ignore import IgnoreResult

LIMITS_PATH = "/api/v2/apps/deploy-limits"
TOP_N = 10


@dataclass
class Limits:
    """Package ceilings. The authoritative values live in platform config."""

    max_package_mb: int
    max_unpacked_mb: int
    max_package_entries: int
    degraded: bool = False


# Fallback only — used when the endpoint cannot answer. Never a hard constant:
# raising the ceiling is an ops change, not a CLI release.
DEFAULT_LIMITS = Limits(max_package_mb=50, max_unpacked_mb=200, max_package_entries=20000, degraded=True)


@dataclass
class SkippedEntry:
    path: str
    kind: str


@dataclass
class PackageStat:
    path: Path
    entry_count: int
    raw_bytes: int
    compressed_bytes: int
    sha256: str
    excluded_count: int
    skipped: list[SkippedEntry] = field(default_factory=list)
    top_files: list[tuple[str, int]] = field(default_factory=list)
    top_dirs: list[tuple[str, int]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def fetch_limits(client: Any) -> Limits:
    """Ask the platform for the ceilings; fall back rather than block.

    Any failure here — endpoint not deployed yet, a flaky hop, the runtime layer
    switched off — must not stop a deploy. The upload proceeds and the server's
    16201 remains the authority. A soft self-check that can kill the main flow is
    worse than no self-check.
    """
    try:
        data = client.get_json(LIMITS_PATH)
    except Exception:
        return Limits(**{**_limits_kwargs(DEFAULT_LIMITS), "degraded": True})
    if not isinstance(data, dict):
        return Limits(**{**_limits_kwargs(DEFAULT_LIMITS), "degraded": True})
    return Limits(
        max_package_mb=int(data.get("max_package_mb", DEFAULT_LIMITS.max_package_mb)),
        max_unpacked_mb=int(data.get("max_unpacked_mb", DEFAULT_LIMITS.max_unpacked_mb)),
        max_package_entries=int(data.get("max_package_entries", DEFAULT_LIMITS.max_package_entries)),
        degraded=False,
    )


def _limits_kwargs(limits: Limits) -> dict[str, Any]:
    return {
        "max_package_mb": limits.max_package_mb,
        "max_unpacked_mb": limits.max_unpacked_mb,
        "max_package_entries": limits.max_package_entries,
    }


def build_package(root: Path, ignore_result: IgnoreResult, out_path: Path) -> PackageStat:
    root = Path(root)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    skipped: list[SkippedEntry] = []
    sizes: list[tuple[str, int]] = []

    with open(out_path, "wb") as raw:
        # mtime=0 and an empty filename keep the gzip header free of anything
        # that changes between two runs of the same content.
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for rel in sorted(ignore_result.files):
                    source = root / rel
                    kind = _special_kind(source)
                    if kind is not None:
                        skipped.append(SkippedEntry(path=rel, kind=kind))
                        continue
                    info = _tar_info(rel, source)
                    sizes.append((rel, info.size))
                    with open(source, "rb") as fh:
                        tar.addfile(info, fh)

    compressed = out_path.stat().st_size
    digest = _sha256(out_path)
    sizes.sort(key=lambda item: item[1], reverse=True)
    return PackageStat(
        path=out_path,
        entry_count=len(sizes),
        raw_bytes=sum(size for _, size in sizes),
        compressed_bytes=compressed,
        sha256=digest,
        excluded_count=ignore_result.excluded_count,
        skipped=skipped,
        top_files=sizes[:TOP_N],
        top_dirs=_top_dirs(sizes),
        notes=list(ignore_result.notes),
    )


def _special_kind(source: Path) -> str | None:
    """Classify anything the server's unpack gate would reject."""
    try:
        st = source.lstat()
    except OSError:
        return "unreadable"
    mode = st.st_mode
    if stat_module.S_ISLNK(mode):
        return "symlink"
    if stat_module.S_ISFIFO(mode):
        return "fifo"
    if stat_module.S_ISCHR(mode) or stat_module.S_ISBLK(mode):
        return "device"
    if stat_module.S_ISSOCK(mode):
        return "socket"
    # A hardlinked regular file is packed like any other file, content and all.
    # Hardlink *members* only appear when tarfile picks the type itself, via
    # ``TarFile.add``/``gettarinfo`` and its inode table; ``_tar_info`` builds a
    # plain REGTYPE header by hand and streams the bytes, so no such member can
    # be produced here. Skipping ``st_nlink > 1`` would drop the contents of an
    # ordinary file for a reason that does not apply to this writer — and
    # ``st_nlink > 1`` is not a property the author chose or can see.
    if not stat_module.S_ISREG(mode):
        return "special"
    return None


def _tar_info(rel: str, source: Path) -> tarfile.TarInfo:
    arcname = str(PurePosixPath(*Path(rel).parts))
    _assert_safe(arcname)
    st = source.stat()
    info = tarfile.TarInfo(arcname)
    info.size = st.st_size
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.type = tarfile.REGTYPE
    info.mode = 0o755 if st.st_mode & stat_module.S_IXUSR else 0o644
    return info


def _assert_safe(arcname: str) -> None:
    if "\\" in arcname or arcname.startswith("/") or arcname.startswith("./") or ".." in arcname.split("/"):
        raise CliError(
            f"包内路径非法：{arcname}",
            exit_code=EXIT_LOCAL_INVALID,
            next_step="这通常意味着项目里有异常文件名，请重命名后重试；这是 CLI 的最后一道防线，请一并报障。",
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _top_dirs(sizes: list[tuple[str, int]]) -> list[tuple[str, int]]:
    totals: dict[str, int] = {}
    for rel, size in sizes:
        top = rel.split("/")[0] if "/" in rel else "(项目根)"
        totals[top] = totals.get(top, 0) + size
    return sorted(totals.items(), key=lambda item: item[1], reverse=True)[:TOP_N]


def check_limits(stat: PackageStat, limits: Limits) -> None:
    """Refuse the whole package when it does not fit. Never trim."""
    reasons = []
    if stat.compressed_bytes > limits.max_package_mb * 1024 * 1024:
        reasons.append(f"压缩后 {_mb(stat.compressed_bytes)} 超过上限 {limits.max_package_mb} MB")
    if stat.raw_bytes > limits.max_unpacked_mb * 1024 * 1024:
        reasons.append(f"解包后 {_mb(stat.raw_bytes)} 超过上限 {limits.max_unpacked_mb} MB")
    if stat.entry_count > limits.max_package_entries:
        reasons.append(f"条目数 {stat.entry_count} 超过上限 {limits.max_package_entries}")
    if not reasons:
        return
    raise CliError(
        "上传包超过平台上限，整包拒绝：" + "；".join(reasons),
        exit_code=EXIT_LOCAL_INVALID,
        next_step="按下面的清单清理后重试（或请运维调整 app_runtime 的包体上限）。\n"
        + format_size_report(stat, limits),
    )


def format_size_report(stat: PackageStat, limits: Limits) -> str:
    """The excluded count comes first, on purpose.

    The first reaction to "package too large" is "the platform limit is too
    small". Nine times out of ten the real answer is an un-ignored `.venv/`, so
    the report opens by saying how much was already dropped before it starts
    naming files.
    """
    lines = [
        f"已排除 {stat.excluded_count} 项（版本控制元数据 / 依赖目录 / 缓存 / 本地数据文件等）",
        f"打包条目 {stat.entry_count} 个，解包后 {_mb(stat.raw_bytes)}，压缩后 {_mb(stat.compressed_bytes)}"
        f"（上限：{limits.max_package_mb} MB / 解包 {limits.max_unpacked_mb} MB / {limits.max_package_entries} 条目）",
    ]
    for note in stat.notes:
        lines.append(f"说明: {note}")
    if stat.skipped:
        lines.append(f"已跳过 {len(stat.skipped)} 个不可打包条目（平台解包闸会拒绝它们）:")
        lines.extend(f"  {entry.path}  [{entry.kind}]" for entry in stat.skipped)
    lines.append("Top 目录:")
    lines.extend(f"  {name}  {_mb(size)}" for name, size in stat.top_dirs)
    lines.append("Top 文件:")
    lines.extend(f"  {name}  {_mb(size)}" for name, size in stat.top_files)
    return "\n".join(lines)


def _mb(size: int) -> str:
    return f"{size / (1024 * 1024):.2f} MB"
