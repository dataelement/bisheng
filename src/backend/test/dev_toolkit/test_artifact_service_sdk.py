"""F057 T024 — the artifact service reads the ``sdk`` half of the manifest.

The SDK wheel rides the same staging directory as the CLI wheel and is written
by a second packing script, so the two halves have to be independent in both
directions: a release that never packed the SDK still serves the CLI, and a
manifest section whose wheel did not survive the checkout degrades to ``None``
rather than advertising a download that 500s on the first byte (AC-01).

``read_sdk_guide`` is here too: the developer guide and the skill pack are one
file (决议-7), so the service reads the pack's ``SKILL.md`` instead of a second
copy that would drift (AC-26).
"""

from __future__ import annotations

import hashlib
import json

from bisheng.dev_toolkit.domain.services import artifact_service
from test.dev_toolkit.conftest import (
    CLI_VERSION,
    MANIFEST_PLATFORM_VERSION,
    SDK_MIN_COMPATIBLE,
    SDK_VERSION,
    SDK_WHEEL_BYTES,
    SDK_WHEEL_NAME,
)


def test_snapshot_reads_sdk_artifact(staged_artifacts):
    snapshot = artifact_service.read_snapshot()

    assert snapshot.sdk is not None
    assert snapshot.sdk.version == SDK_VERSION
    assert snapshot.sdk.min_compatible == SDK_MIN_COMPATIBLE
    assert snapshot.sdk.filename == SDK_WHEEL_NAME
    assert snapshot.sdk.sha256 == hashlib.sha256(SDK_WHEEL_BYTES).hexdigest()
    assert snapshot.sdk.path == staged_artifacts / SDK_WHEEL_NAME
    # The two halves are read in the same pass and neither shadows the other.
    assert snapshot.cli is not None and snapshot.cli.version == CLI_VERSION
    assert snapshot.platform_version == MANIFEST_PLATFORM_VERSION


def test_sdk_none_when_section_absent_cli_still_present(staged_cli_only):
    """An F053-era deployment: manifest has no ``sdk`` key at all."""
    snapshot = artifact_service.read_snapshot()

    assert snapshot.sdk is None
    assert snapshot.cli is not None
    assert snapshot.cli.version == CLI_VERSION


def test_sdk_none_when_wheel_file_missing(staged_artifacts):
    """Manifest advertises a wheel the checkout does not carry (a partial rsync).

    Trusting the manifest alone would hand pip a download path that fails on the
    first byte, and the CLI half must not be dragged down with it.
    """
    (staged_artifacts / SDK_WHEEL_NAME).unlink()

    snapshot = artifact_service.read_snapshot()

    assert snapshot.sdk is None
    assert snapshot.cli is not None


def test_min_compatible_defaults_to_version(staged_artifacts):
    """A manifest written before the key existed declares itself its own floor."""
    manifest_path = staged_artifacts / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["sdk"]["min_compatible"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    snapshot = artifact_service.read_snapshot()

    assert snapshot.sdk is not None
    assert snapshot.sdk.min_compatible == SDK_VERSION


def test_read_sdk_guide_returns_the_platform_wiring_skill_md():
    """One source for guide and skill pack — not a second copy that drifts."""
    guide = artifact_service.read_sdk_guide()

    assert guide is not None
    expected = (artifact_service.SKILLS_DIR / "platform-wiring" / "SKILL.md").read_text(encoding="utf-8")
    assert guide == expected


def test_read_sdk_guide_is_none_when_the_pack_is_absent(monkeypatch, tmp_path):
    """A release shipping no pack degrades to ``None`` so the endpoint can 404 readably."""
    monkeypatch.setattr(artifact_service, "SKILLS_DIR", tmp_path / "no-skills")

    assert artifact_service.read_sdk_guide() is None
