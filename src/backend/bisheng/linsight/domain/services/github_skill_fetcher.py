"""Fetch a skill bundle from a public GitHub directory (F035, GitHub-import increment).

The pasted GitHub web URL is parsed into ``owner/repo/ref/subpath`` and the target
directory is walked recursively through the GitHub Contents API. Each file's raw
bytes are pulled from its ``download_url`` (raw.githubusercontent.com) — this keeps
binary assets intact and, because the raw CDN does not count against the API rate
limit, only the per-directory listing calls do.

The returned ``{relative_path: bytes}`` map (SKILL.md rebased to the root) feeds the
exact same ``SkillService._create`` chain as the local-upload path, so validation,
duplicate checks, disk write and the owner tuple are all reused.

Scope (aligned with the approved plan): GitHub only, anonymous access, no proxy/token
config. ``httpx`` honours standard ``HTTP(S)_PROXY`` env vars via ``trust_env`` without
any extra configuration. Branch names containing slashes are not supported (the first
path segment after ``tree``/``blob`` is taken as the ref, matching the upstream design).
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, urlparse

import httpx
from loguru import logger

from bisheng.common.errcode.linsight import (
    SkillFileTooLargeError,
    SkillGitHubFetchError,
    SkillGitHubRateLimitError,
    SkillGitHubUrlInvalidError,
    SkillValidationError,
)
from bisheng.linsight.domain.services.skill_store import MAX_BUNDLE_SIZE, SKILL_MD

GITHUB_HOSTS = {"github.com", "www.github.com"}
RAW_HOSTS = {"raw.githubusercontent.com", "codeload.github.com"}
GITHUB_API = "https://api.github.com"

MAX_DEPTH = 5  # directory nesting guard
MAX_FILES = 200  # file-count guard against pulling a runaway tree
TIMEOUT = 30  # seconds, per request

_CLIENT_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    # GitHub rejects API requests without a User-Agent; identify ourselves explicitly.
    "User-Agent": "bisheng-linsight-skill-importer",
}


@dataclass
class GithubTarget:
    owner: str
    repo: str
    ref: str  # "" means the repository's default branch
    subpath: str  # "" means the repository root


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
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise SkillGitHubUrlInvalidError(msg="URL must start with https://")
    if parsed.netloc.lower() not in GITHUB_HOSTS:
        raise SkillGitHubUrlInvalidError(msg="only public github.com URLs are supported")

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise SkillGitHubUrlInvalidError()
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise SkillGitHubUrlInvalidError()

    rest = parts[2:]
    if not rest:
        return GithubTarget(owner=owner, repo=repo, ref="", subpath="")

    marker = rest[0]
    if marker == "tree" and len(rest) >= 2:
        return GithubTarget(owner=owner, repo=repo, ref=rest[1], subpath="/".join(rest[2:]))
    if marker == "blob" and len(rest) >= 3:
        blob_parts = rest[2:]
        if blob_parts[-1].upper() != SKILL_MD.upper():
            raise SkillGitHubUrlInvalidError(msg="a blob URL must point to a SKILL.md file")
        return GithubTarget(owner=owner, repo=repo, ref=rest[1], subpath="/".join(blob_parts[:-1]))
    raise SkillGitHubUrlInvalidError()


async def fetch_skill_files(target: GithubTarget) -> dict[str, bytes]:
    """Recursively download the target directory into ``{relative_path: bytes}``.

    Keys are rebased relative to ``target.subpath`` so SKILL.md lands at the root.
    Whether SKILL.md actually exists is asserted (fail-fast) at the top level.
    """
    files: dict[str, bytes] = {}
    total_size = 0

    async def walk(client: httpx.AsyncClient, dir_path: str, rel_prefix: str, depth: int) -> None:
        nonlocal total_size
        if depth > MAX_DEPTH:
            raise SkillGitHubFetchError(msg=f"directory nesting exceeds {MAX_DEPTH} levels")

        items = await _list_dir(client, target, dir_path)

        if depth == 0 and not any(
            it.get("type") == "file" and (it.get("name") or "").upper() == SKILL_MD.upper() for it in items
        ):
            # No SKILL.md at the root — fail before walking into subdirectories so a
            # repo-root URL never drags the whole tree down. Reuses the upload semantics.
            raise SkillValidationError(msg="SKILL.md not found at the root of the GitHub directory")

        for item in items:
            name = item.get("name") or ""
            itype = item.get("type")
            rel = f"{rel_prefix}/{name}" if rel_prefix else name
            if itype == "dir":
                await walk(client, item.get("path") or f"{dir_path}/{name}", rel, depth + 1)
            elif itype == "file":
                if len(files) >= MAX_FILES:
                    raise SkillGitHubFetchError(msg=f"skill directory has more than {MAX_FILES} files")
                total_size += int(item.get("size") or 0)
                if total_size > MAX_BUNDLE_SIZE:
                    raise SkillFileTooLargeError()
                files[rel] = await _download_raw(client, item.get("download_url"))
            # symlinks / submodules are intentionally ignored — not portable as bundle assets.

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers=_CLIENT_HEADERS) as client:
            await walk(client, target.subpath, "", 0)
    except httpx.HTTPError as exc:
        # Connection/timeout/transport errors — surface a clean domain error, never the raw cause.
        logger.warning("github skill fetch transport error: {}", exc)
        raise SkillGitHubFetchError()
    return files


async def _list_dir(client: httpx.AsyncClient, target: GithubTarget, dir_path: str) -> list[dict]:
    url = f"{GITHUB_API}/repos/{target.owner}/{target.repo}/contents/{quote(dir_path, safe='/')}"
    params = {"ref": target.ref} if target.ref else None
    resp = await client.get(url, params=params)
    _raise_for_contents_status(resp)
    data = resp.json()
    # A path that resolves to a single file (not a directory) comes back as an object.
    return [data] if isinstance(data, dict) else data


async def _download_raw(client: httpx.AsyncClient, download_url: str | None) -> bytes:
    if not download_url:
        raise SkillGitHubFetchError(msg="file is missing a download URL")
    host = urlparse(download_url).netloc.lower()
    if host not in RAW_HOSTS:
        # Defence in depth: only ever pull bytes from GitHub's raw hosts.
        raise SkillGitHubFetchError(msg=f"refusing to download from unexpected host: {host}")
    resp = await client.get(download_url)
    if resp.status_code != 200:
        raise SkillGitHubFetchError(msg=f"failed to download file ({resp.status_code})")
    return resp.content


def _raise_for_contents_status(resp: httpx.Response) -> None:
    if resp.status_code == 200:
        return
    if resp.status_code == 404:
        # Private repos also answer 404 to anonymous callers (existence not leaked).
        raise SkillGitHubFetchError(msg="repository, branch or path not found")
    if resp.status_code in (403, 429):
        # For anonymous access a 403 is almost always the hourly rate limit.
        raise SkillGitHubRateLimitError()
    raise SkillGitHubFetchError(msg=f"GitHub API returned {resp.status_code}")
