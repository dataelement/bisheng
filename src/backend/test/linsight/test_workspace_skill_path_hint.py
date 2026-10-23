"""A read that misses names the skill folder holding the file.

Incident 2026-10-23 (106, svid 4c85fb69…): SKILL.md listed ``references/…`` files,
the model read ``/references/…``, got a bare "not found" three times, and redid a
30k-character analysis after each miss. The hint is text only: the read never
switches to another path.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from __future__ import annotations

import tempfile

import pytest
from test_workspace_backend import FakeMinioStorage

from bisheng.linsight.domain.services.tool_loop_middleware import _corrective_hint
from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend

SVID = "4c85fb6948a44258a9cc8fa7f336fbb4"
MANIFEST = "references/power_phase1_llm_operation_manifest.json"


@pytest.fixture()
def backend():
    with tempfile.TemporaryDirectory() as workdir:
        ws = WorkspaceBackend(svid=SVID, minio=FakeMinioStorage(), file_dir=workdir)
        ws.upload_files(
            [
                (f"/skills/credit-report-llm-refresh/{MANIFEST}", b"{}"),
                ("/skills/credit-report-llm-refresh/SKILL.md", b"---\nname: x\n---\n"),
            ]
        )
        yield ws


def test_root_relative_read_names_the_skill_path(backend):
    error = backend.read(f"/{MANIFEST}").error

    assert f"File '/{MANIFEST}' not found." in error
    assert f"'/skills/credit-report-llm-refresh/{MANIFEST}'" in error


async def test_async_read_names_the_skill_path_too(backend):
    error = (await backend.aread(MANIFEST)).error

    assert f"'/skills/credit-report-llm-refresh/{MANIFEST}'" in error


def test_every_skill_holding_the_file_is_listed(backend):
    backend.upload_files([("/skills/another-skill/SKILL.md", b"---\nname: y\n---\n")])
    error = backend.read("/SKILL.md").error

    assert "'/skills/another-skill/SKILL.md', '/skills/credit-report-llm-refresh/SKILL.md'" in error


def test_a_file_no_skill_has_keeps_the_plain_message(backend):
    assert backend.read("/references/absent.md").error == "File '/references/absent.md' not found"


def test_a_miss_inside_skills_is_not_redirected(backend):
    error = backend.read("/skills/credit-report-llm-refresh/references/absent.md").error

    assert error == "File '/skills/credit-report-llm-refresh/references/absent.md' not found"


def test_edit_does_not_point_at_the_read_only_skill_folder(backend):
    error = backend.edit(f"/{MANIFEST}", "a", "b").error

    assert "/skills/" not in error


def test_repeated_failure_hint_names_the_path_cause():
    hint = _corrective_hint("read_file")

    assert "核对路径" in hint
    assert "必填项" in hint
