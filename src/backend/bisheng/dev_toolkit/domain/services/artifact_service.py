"""Reads the CLI build artifacts that travel inside the backend package.

``scripts/pack_cli_wheel.sh`` builds the wheel from ``src/bisheng-cli/`` and
stages it here together with a ``manifest.json``. It has to live inside the
package — the backend image's build context is only ``src/backend/``
(``ci.yml`` + ``Dockerfile``'s ``COPY ./ ./``), so ``src/bisheng-cli/`` is not
in the image at all. Same judgement as ``linsight/builtin_skills/``: keeping it
inside the package means every deployment shape (docker COPY, rsync, pip
install) carries it automatically.

**Missing artifacts are a normal branch, not a failure.** A checkout that never
ran the packing script has no wheel and no manifest, and so does a release where
someone forgot to commit the build output. Both are release problems, and both
must read like one: this module answers ``None`` and lets the endpoints degrade
readably. Raising instead would dress "the artifact was not committed" up as
"the platform is broken", and a traceback in the logs would send whoever is on
call looking in the wrong place entirely.

Nothing here touches the database. The version numbers are a property of the
build, not of any tenant, which is what lets the endpoints stay anonymous.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

# ``bisheng/dev_toolkit/artifacts/`` — resolved from this file so it follows the
# package wherever it is installed. The directory name must stay ``artifacts``:
# ``.gitignore`` carries ``build/``, ``lib/``, ``wheels/`` and ``sdist/`` without
# a leading slash, so those names are ignored at every depth and ``git add``
# would fail silently on the very artifact the image needs.
ARTIFACTS_DIR = Path(__file__).resolve().parents[2] / "artifacts"

MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class CliArtifact:
    """One installable CLI wheel plus the metadata a client needs before downloading."""

    version: str
    min_compatible: str
    filename: str
    sha256: str
    path: Path


@dataclass(frozen=True)
class DistributionSnapshot:
    """Everything the distribution endpoints know, read in one pass over the disk.

    ``cli`` is ``None`` when the artifacts were never packed or never committed.
    ``platform_version`` comes from the manifest as well, deliberately *not* from
    ``bisheng.__version__`` — that one is a hardcoded literal in source and would
    make every compatibility comparison meaningless.
    """

    cli: CliArtifact | None
    platform_version: str | None


def _read_manifest() -> dict | None:
    """Parsed ``manifest.json``, or ``None`` when it is absent or unreadable."""
    manifest_path = ARTIFACTS_DIR / MANIFEST_NAME
    if not manifest_path.is_file():
        return None
    try:
        content = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        # A corrupt manifest is the same class of problem as a missing one — the
        # build output is not usable — so it degrades the same way instead of
        # 500ing. Logged at exception level because, unlike "never packed", this
        # one is genuinely unexpected and worth a traceback.
        logger.exception("dev_toolkit manifest at {} is unreadable; serving the degraded payload", manifest_path)
        return None
    return content if isinstance(content, dict) else None


def read_snapshot() -> DistributionSnapshot:
    """Read the staged artifacts. Never raises for a missing or partial staging area."""
    manifest = _read_manifest()
    if manifest is None:
        return DistributionSnapshot(cli=None, platform_version=None)

    platform_version = (manifest.get("platform") or {}).get("version")
    cli_meta = manifest.get("cli") or {}
    filename = cli_meta.get("filename")
    version = cli_meta.get("version")

    if not filename or not version:
        return DistributionSnapshot(cli=None, platform_version=platform_version)

    # The manifest and the wheel are committed together, but a partial checkout
    # (or a partial rsync) can carry one without the other. Trusting the manifest
    # alone would hand out a download path that 500s on the first byte.
    wheel_path = ARTIFACTS_DIR / Path(filename).name
    if not wheel_path.is_file():
        logger.warning(
            "dev_toolkit manifest advertises {} but the file is not in {}; serving the degraded payload",
            filename,
            ARTIFACTS_DIR,
        )
        return DistributionSnapshot(cli=None, platform_version=platform_version)

    return DistributionSnapshot(
        cli=CliArtifact(
            version=version,
            # A release that predates the min_compatible key is compatible with
            # itself and nothing older, which is what falling back to `version`
            # expresses.
            min_compatible=cli_meta.get("min_compatible") or version,
            filename=wheel_path.name,
            sha256=cli_meta.get("sha256") or "",
            path=wheel_path,
        ),
        platform_version=platform_version,
    )
