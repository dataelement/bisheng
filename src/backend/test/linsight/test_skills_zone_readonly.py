"""The provisioned ``skills/`` subtree must be read-only to the model.

Observed on a customer run (session c139f849…): asked for a PPT, the agent's
FOURTH tool call was ``write_file`` on ``/skills/bisheng-pptx/SKILL.md``, replacing
the shipped 13.5 KB skill with a 1.3 KB doc it made up — one that instructed it to
``from bisheng_pptx import create_presentation``, a module that does not exist. The
next call read that fabrication back and the run followed it, ending in a 310-byte
text file named ``presentation.pptx``.

Two things make this worth a hard block rather than a prompt line. The bundle is
platform-provided content the model is supposed to OBEY, so letting it rewrite its
own instructions removes the only ground truth in the run. And the rewritten copy
is what lands in the session snapshot, so a later investigation reads the model's
invention and concludes the skill itself was broken.

``upload_files`` stays open on purpose: that is the platform's own copy-in path
(``skill_provisioning.materialize_session_skills``), not a model tool.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from unittest.mock import MagicMock

from bisheng.linsight.domain.services.workspace_backend import (
    SKILLS_READONLY_ERROR_PREFIX,
    WorkspaceBackend,
)


def _backend(tmp_path) -> WorkspaceBackend:
    minio = MagicMock()
    minio.bucket = "bisheng"
    return WorkspaceBackend(svid="sv-skills", minio=minio, file_dir=str(tmp_path))


def _seed(backend: WorkspaceBackend, rel: str, data: bytes) -> None:
    backend._cache_write(rel, data)


# ---------------------------------------------------------------------------
# write / awrite
# ---------------------------------------------------------------------------
def test_write_into_a_skill_bundle_is_refused(tmp_path):
    backend = _backend(tmp_path)
    result = backend.write("/skills/bisheng-pptx/SKILL.md", "# my own version")
    assert result.error is not None
    assert SKILLS_READONLY_ERROR_PREFIX in result.error
    # Refused BEFORE any I/O: neither the cache nor MinIO may carry the new bytes.
    assert backend._cache_read("skills/bisheng-pptx/SKILL.md") is None
    backend.minio.put_object_sync.assert_not_called()


async def test_awrite_into_a_skill_bundle_is_refused(tmp_path):
    """The async path is the one the agent actually takes — guarding only the sync
    twin would leave the real hole open."""
    backend = _backend(tmp_path)
    result = await backend.awrite("/skills/bisheng-pptx/scripts/pptx_helpers.py", "raise SystemExit")
    assert result.error is not None
    assert SKILLS_READONLY_ERROR_PREFIX in result.error
    backend.minio.put_object.assert_not_called()


def test_the_skills_root_itself_is_refused(tmp_path):
    backend = _backend(tmp_path)
    assert backend.write("/skills", "x").error is not None


def test_a_path_merely_starting_with_the_word_skills_is_allowed(tmp_path):
    """``skills-notes.md`` is a root-level file, not the skills zone. Prefix
    matching without the separator would silently swallow it."""
    backend = _backend(tmp_path)
    assert backend.write("/skills-notes.md", "notes").error is None
    assert backend.write("/output/skills.md", "notes").error is None


# ---------------------------------------------------------------------------
# edit / aedit
# ---------------------------------------------------------------------------
def test_edit_of_a_skill_file_is_refused(tmp_path):
    """``edit_file`` is the second way in, and the more insidious one: a targeted
    replacement leaves the bundle looking untouched everywhere it is not read."""
    backend = _backend(tmp_path)
    _seed(backend, "skills/bisheng-pptx/SKILL.md", b"# real skill\nrun the build script\n")
    result = backend.edit("/skills/bisheng-pptx/SKILL.md", "run the build script", "make it up")
    assert result.error is not None
    assert SKILLS_READONLY_ERROR_PREFIX in result.error
    assert backend._cache_read("skills/bisheng-pptx/SKILL.md") == b"# real skill\nrun the build script\n"


async def test_aedit_of_a_skill_file_is_refused(tmp_path):
    backend = _backend(tmp_path)
    _seed(backend, "skills/bisheng-docx/SKILL.md", b"# real skill\n")
    result = await backend.aedit("/skills/bisheng-docx/SKILL.md", "real", "fake")
    assert result.error is not None


# ---------------------------------------------------------------------------
# the paths that must stay open
# ---------------------------------------------------------------------------
def test_output_and_scratch_writes_still_work(tmp_path):
    backend = _backend(tmp_path)
    assert backend.write("/output/报告.md", "# 报告").error is None
    assert backend.write("/scratch/notes.txt", "notes").error is None


def test_provisioning_can_still_copy_bundles_in(tmp_path):
    """``materialize_session_skills`` writes the bundle through ``upload_files``.
    Blocking that would leave every run with no skills at all."""
    backend = _backend(tmp_path)
    responses = backend.upload_files([("/skills/bisheng-pptx/SKILL.md", b"# the real skill")])
    assert all(getattr(r, "error", None) is None for r in responses)
    assert backend._cache_read("skills/bisheng-pptx/SKILL.md") == b"# the real skill"


def test_reading_a_skill_file_still_works(tmp_path):
    backend = _backend(tmp_path)
    _seed(backend, "skills/bisheng-pptx/SKILL.md", b"# the real skill")
    result = backend.read("/skills/bisheng-pptx/SKILL.md")
    assert result.error is None
    assert "the real skill" in result.file_data["content"]
