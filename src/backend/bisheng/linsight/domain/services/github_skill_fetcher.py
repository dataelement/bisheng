"""Fetch a skill bundle from a public GitHub or Gitee directory.

The pasted web URL is parsed into ``owner/repo/ref/subpath`` and the target directory
is walked through that host's contents API. Each file's raw bytes are pulled from its
``download_url`` so binary assets stay intact. Directory listings are the only calls
that count against the API rate limit.

The returned ``{relative_path: bytes}`` map (SKILL.md rebased to the root) feeds the
exact same ``SkillService._create`` chain as the local-upload path, so validation,
duplicate checks, disk write and the owner tuple are all reused.

Anonymous access only: no token or proxy setting. ``httpx`` honours standard
``HTTP(S)_PROXY`` env vars via ``trust_env``. Branch names containing slashes are not
supported (the first path segment after ``tree``/``blob`` is the ref).
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, urlparse

import httpx
from loguru import logger

from bisheng.common.errcode.linsight import (
    SkillBundleTooLargeError,
    SkillGiteeFetchError,
    SkillGiteeRateLimitError,
    SkillGiteeUrlInvalidError,
    SkillGitHubFetchError,
    SkillGitHubRateLimitError,
    SkillGitHubUrlInvalidError,
    SkillValidationError,
)
from bisheng.linsight.domain.services.skill_store import SKILL_MD, resolve_skill_unpacked_limit

GITHUB_HOSTS = {"github.com", "www.github.com"}
GITEE_HOSTS = {"gitee.com", "www.gitee.com"}
RAW_HOSTS = {"raw.githubusercontent.com", "codeload.github.com"}
GITEE_RAW_HOSTS = {"gitee.com", "www.gitee.com", "raw.giteeusercontent.com"}
GITHUB_API = "https://api.github.com"
GITEE_API = "https://gitee.com/api/v5"

MAX_DEPTH = 5  # directory nesting guard
MAX_FILES = 200  # file-count guard against pulling a runaway tree
TIMEOUT = 30  # seconds, per request

_USER_AGENT = "bisheng-linsight-skill-importer"
_GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    # GitHub rejects API requests without a User-Agent; identify ourselves explicitly.
    "User-Agent": _USER_AGENT,
}
_GITEE_HEADERS = {"Accept": "application/json", "User-Agent": _USER_AGENT}


@dataclass(frozen=True)
class _HostSpec:
    name: str
    api: str
    raw_hosts: frozenset[str]
    headers: dict[str, str]
    fetch_error: type
    rate_error: type
    label: str


_HOSTS = {
    "github": _HostSpec(
        name="github",
        api=GITHUB_API,
        raw_hosts=frozenset(RAW_HOSTS),
        headers=_GITHUB_HEADERS,
        fetch_error=SkillGitHubFetchError,
        rate_error=SkillGitHubRateLimitError,
        label="GitHub",
    ),
    "gitee": _HostSpec(
        name="gitee",
        api=GITEE_API,
        raw_hosts=frozenset(GITEE_RAW_HOSTS),
        headers=_GITEE_HEADERS,
        fetch_error=SkillGiteeFetchError,
        rate_error=SkillGiteeRateLimitError,
        label="Gitee",
    ),
}


@dataclass
class GithubTarget:
    """A public GitHub or Gitee directory. ``host`` defaults to GitHub."""

    owner: str
    repo: str
    ref: str  # "" means the repository's default branch
    subpath: str  # "" means the repository root
    host: str = "github"


def parse_github_url(url: str) -> GithubTarget:
    """Parse a public GitHub web URL into its components.

    Supported shapes::

        https://github.com/{owner}/{repo}/tree/{ref}/{subpath...}
        https://github.com/{owner}/{repo}/tree/{ref}
        https://github.com/{owner}/{repo}                     # default branch, repo root
        https://github.com/{owner}/{repo}/blob/{ref}/{.../SKILL.md}   # parent dir is the skill

    Raises ``SkillGitHubUrlInvalidError`` for anything else (wrong host, non-https,
    blob pointing at a non-SKILL.md file, etc.).
    """
    return _parse_repo_url(
        url,
        hosts=GITHUB_HOSTS,
        invalid=SkillGitHubUrlInvalidError,
        host_name="github",
        host_msg="only public github.com URLs are supported",
    )


def parse_gitee_url(url: str) -> GithubTarget:
    """Parse a public Gitee web URL. Shapes match :func:`parse_github_url`."""
    return _parse_repo_url(
        url,
        hosts=GITEE_HOSTS,
        invalid=SkillGiteeUrlInvalidError,
        host_name="gitee",
        host_msg="only public gitee.com URLs are supported",
    )


def _parse_repo_url(url: str, *, hosts: set[str], invalid, host_name: str, host_msg: str) -> GithubTarget:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise invalid(msg="URL must start with https://")
    if parsed.netloc.lower() not in hosts:
        raise invalid(msg=host_msg)

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise invalid()
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise invalid()

    rest = parts[2:]
    if not rest:
        return GithubTarget(owner=owner, repo=repo, ref="", subpath="", host=host_name)

    marker = rest[0]
    if marker == "tree" and len(rest) >= 2:
        return GithubTarget(owner=owner, repo=repo, ref=rest[1], subpath="/".join(rest[2:]), host=host_name)
    if marker == "blob" and len(rest) >= 3:
        blob_parts = rest[2:]
        if blob_parts[-1].upper() != SKILL_MD.upper():
            raise invalid(msg="a blob URL must point to a SKILL.md file")
        return GithubTarget(owner=owner, repo=repo, ref=rest[1], subpath="/".join(blob_parts[:-1]), host=host_name)
    raise invalid()


async def fetch_skill_files(target: GithubTarget) -> dict[str, bytes]:
    """Recursively download the target directory into ``{relative_path: bytes}``.

    Keys are rebased relative to ``target.subpath`` so SKILL.md lands at the root.
    Whether SKILL.md actually exists is asserted (fail-fast) at the top level.
    """
    spec = _HOSTS[target.host]
    files: dict[str, bytes] = {}
    total_size = 0
    max_unpacked = await resolve_skill_unpacked_limit()

    async def walk(client: httpx.AsyncClient, dir_path: str, rel_prefix: str, depth: int) -> None:
        nonlocal total_size
        if depth > MAX_DEPTH:
            raise spec.fetch_error(msg=f"directory nesting exceeds {MAX_DEPTH} levels")

        items = await _list_dir(client, target, spec, dir_path)

        if depth == 0 and not any(
            it.get("type") == "file" and (it.get("name") or "").upper() == SKILL_MD.upper() for it in items
        ):
            # No SKILL.md at the root — fail before walking into subdirectories so a
            # repo-root URL never drags the whole tree down. Reuses the upload semantics.
            raise SkillValidationError(msg=f"SKILL.md not found at the root of the {spec.label} directory")

        for item in items:
            name = item.get("name") or ""
            itype = item.get("type")
            rel = f"{rel_prefix}/{name}" if rel_prefix else name
            if itype == "dir":
                await walk(client, item.get("path") or f"{dir_path}/{name}", rel, depth + 1)
            elif itype == "file":
                if len(files) >= MAX_FILES:
                    raise spec.fetch_error(msg=f"skill directory has more than {MAX_FILES} files")
                total_size += int(item.get("size") or 0)
                # Raw file sizes — unpacked semantics, so this shares the upload path's
                # unpacked limit rather than the (compressed) upload payload limit.
                if total_size > max_unpacked:
                    raise SkillBundleTooLargeError(limit_mb=max_unpacked // (1024 * 1024))
                files[rel] = await _download_raw(client, item.get("download_url"), spec)
            # symlinks / submodules are intentionally ignored — not portable as bundle assets.

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers=spec.headers) as client:
            await walk(client, target.subpath, "", 0)
    except httpx.HTTPError as exc:
        # Connection/timeout/transport errors — surface a clean domain error, never the raw cause.
        logger.warning("skill repo fetch transport error host={}: {}", target.host, exc)
        raise spec.fetch_error()
    return files


async def _list_dir(client: httpx.AsyncClient, target: GithubTarget, spec: _HostSpec, dir_path: str) -> list[dict]:
    url = f"{spec.api}/repos/{target.owner}/{target.repo}/contents/{quote(dir_path, safe='/')}"
    params = {"ref": target.ref} if target.ref else None
    resp = await client.get(url, params=params)
    _raise_for_contents_status(resp, spec)
    data = resp.json()
    # A path that resolves to a single file (not a directory) comes back as an object.
    return [data] if isinstance(data, dict) else data


async def _download_raw(client: httpx.AsyncClient, download_url: str | None, spec: _HostSpec) -> bytes:
    if not download_url:
        raise spec.fetch_error(msg="file is missing a download URL")
    host = urlparse(download_url).netloc.lower()
    if host not in spec.raw_hosts:
        # Defence in depth: only ever pull bytes from that host's raw CDN.
        raise spec.fetch_error(msg=f"refusing to download from unexpected host: {host}")
    resp = await client.get(download_url)
    final_host = _response_host(resp)
    # Gitee's download_url on gitee.com redirects to raw.giteeusercontent.com.
    if final_host and final_host not in spec.raw_hosts:
        raise spec.fetch_error(msg=f"refusing to download from unexpected host: {final_host}")
    if resp.status_code != 200:
        raise spec.fetch_error(msg=f"failed to download file ({resp.status_code})")
    return resp.content


def _response_host(resp: httpx.Response) -> str:
    url = getattr(resp, "url", None)
    if url is None:
        return ""
    host = getattr(url, "host", None)
    return (host or urlparse(str(url)).netloc).lower()


def _raise_for_contents_status(resp: httpx.Response, spec: _HostSpec) -> None:
    if resp.status_code == 200:
        return
    if resp.status_code == 404:
        # Private repos also answer 404 to anonymous callers (existence not leaked).
        raise spec.fetch_error(msg="repository, branch or path not found")
    if resp.status_code in (403, 429):
        # For anonymous access a 403 is almost always the hourly rate limit.
        raise spec.rate_error()
    raise spec.fetch_error(msg=f"{spec.label} API returned {resp.status_code}")
