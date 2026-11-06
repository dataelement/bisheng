"""A copied skill that was disabled or deleted is refused on the next read or run.

The directory stays on disk. Content already handed to the model is not taken
back. A same-named tenant skill that is still enabled does not unlock the
directory: the snapshot id is the row that owns these files.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain_core.messages import ToolMessage

from bisheng.linsight.domain.services.agent_factory import SkillSelectionMiddleware
from bisheng.linsight.domain.services.skill_runtime_guard import (
    SKILL_USE_REFUSAL,
    skill_names_in_code,
)
from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend

PERSONAL_ID = 7
ENTERPRISE_ID = 9


def _backend(tmp_path) -> WorkspaceBackend:
    minio = MagicMock()
    minio.bucket = "bisheng"
    backend = WorkspaceBackend(svid="sv-guard", minio=minio, file_dir=str(tmp_path))
    backend.skill_snapshot = [{"name": "pdf", "skill_id": PERSONAL_ID, "owner_user_id": 3, "content_hash": "abc"}]
    return backend


def _seed(backend: WorkspaceBackend, rel: str, data: bytes) -> None:
    backend._cache_write(rel, data)


def _rows(mapping: dict[int, bool | None]):
    def enabled(skill_id: int) -> bool | None:
        return mapping.get(skill_id)

    return enabled


def test_reading_a_disabled_skill_is_refused_and_the_file_stays(tmp_path):
    backend = _backend(tmp_path)
    backend.skill_row_enabled = _rows({PERSONAL_ID: False, ENTERPRISE_ID: True})
    _seed(backend, "skills/pdf/SKILL.md", b"# personal copy\n")
    result = backend.read("/skills/pdf/SKILL.md")
    assert result.error == SKILL_USE_REFUSAL.format(name="pdf")
    assert "Traceback" not in result.error
    assert backend._cache_read("skills/pdf/SKILL.md") == b"# personal copy\n"


async def test_aread_of_a_deleted_skill_is_refused(tmp_path):
    backend = _backend(tmp_path)
    backend.skill_row_enabled = _rows({})
    _seed(backend, "skills/pdf/who.txt", b"who\n")
    result = await backend.aread("/skills/pdf/who.txt")
    assert result.error == SKILL_USE_REFUSAL.format(name="pdf")
    assert backend._cache_read("skills/pdf/who.txt") == b"who\n"


def test_an_enabled_same_named_tenant_skill_does_not_unlock_the_copy(tmp_path):
    """Lookup is the snapshot id. The tenant row being on is a different id."""
    backend = _backend(tmp_path)
    seen = []

    def enabled(skill_id: int) -> bool | None:
        seen.append(skill_id)
        return {PERSONAL_ID: False, ENTERPRISE_ID: True}[skill_id]

    backend.skill_row_enabled = enabled
    _seed(backend, "skills/pdf/SKILL.md", b"# personal copy\n")
    assert backend.read("/skills/pdf/SKILL.md").error == SKILL_USE_REFUSAL.format(name="pdf")
    assert seen == [PERSONAL_ID]


def test_a_path_outside_the_snapshot_is_not_blocked(tmp_path):
    backend = _backend(tmp_path)
    backend.skill_row_enabled = _rows({PERSONAL_ID: False})
    _seed(backend, "skills/other/SKILL.md", b"# other\n")
    _seed(backend, "skills-notes.md", b"notes\n")
    other = backend.read("/skills/other/SKILL.md")
    notes = backend.read("/skills-notes.md")
    assert other.error is None
    assert "other" in other.file_data["content"]
    assert notes.error is None
    assert "notes" in notes.file_data["content"]


def test_an_enabled_snapshot_row_can_still_be_read(tmp_path):
    backend = _backend(tmp_path)
    backend.skill_row_enabled = _rows({PERSONAL_ID: True})
    _seed(backend, "skills/pdf/SKILL.md", b"# still on\n")
    result = backend.read("/skills/pdf/SKILL.md")
    assert result.error is None
    assert "still on" in result.file_data["content"]


def test_content_already_returned_is_not_taken_back(tmp_path):
    backend = _backend(tmp_path)
    backend.skill_row_enabled = _rows({PERSONAL_ID: True})
    _seed(backend, "skills/pdf/SKILL.md", b"# handed over\n")
    first = backend.read("/skills/pdf/SKILL.md")
    handed = first.file_data["content"]
    backend.skill_row_enabled = _rows({PERSONAL_ID: False})
    second = backend.read("/skills/pdf/SKILL.md")
    assert second.error == SKILL_USE_REFUSAL.format(name="pdf")
    assert "handed over" in handed
    assert backend._cache_read("skills/pdf/SKILL.md") == b"# handed over\n"


def test_no_snapshot_still_reads_the_skills_zone(tmp_path):
    minio = MagicMock()
    minio.bucket = "bisheng"
    backend = WorkspaceBackend(svid="sv-old", minio=minio, file_dir=str(tmp_path))
    _seed(backend, "skills/pdf/SKILL.md", b"# old session\n")
    result = backend.read("/skills/pdf/SKILL.md")
    assert result.error is None
    assert "old session" in result.file_data["content"]


def test_code_scan_matches_a_skill_directory_and_not_a_lookalike_name():
    code = 'open("skills/pdf/who.txt")\nopen("/skills/he-tong/a.py")\nopen("skills-notes/x")\nopen("not_skills/pdf/a")'
    assert skill_names_in_code(code) == ["pdf", "he-tong"]


def _selection(enabled) -> SkillSelectionMiddleware:
    session = SimpleNamespace(
        skill_snapshot=[{"name": "pdf", "skill_id": PERSONAL_ID, "owner_user_id": 3, "content_hash": "abc"}]
    )
    return SkillSelectionMiddleware(
        selected_names=["pdf"],
        tool_names={"bisheng_code_interpreter"},
        session=session,
        skill_row_enabled=enabled,
    )


def _code_request(code: str):
    return SimpleNamespace(
        tool_call={"name": "bisheng_code_interpreter", "id": "call-code", "args": {"python_code": code}},
        tool=object(),
        state={},
    )


def test_code_that_opens_a_disabled_skill_is_refused_before_it_runs():
    selection = _selection(_rows({PERSONAL_ID: False, ENTERPRISE_ID: True}))

    def handler(_request):
        raise AssertionError("interpreter ran")

    message = selection.wrap_tool_call(_code_request('open("skills/pdf/who.txt")'), handler)
    assert isinstance(message, ToolMessage)
    assert message.content == SKILL_USE_REFUSAL.format(name="pdf")
    assert "Traceback" not in message.content
    assert message.status != "error"


async def test_async_code_that_opens_a_deleted_skill_is_refused():
    selection = _selection(_rows({}))

    async def handler(_request):
        raise AssertionError("interpreter ran")

    message = await selection.awrap_tool_call(_code_request("p = '/skills/pdf/SKILL.md'"), handler)
    assert message.content == SKILL_USE_REFUSAL.format(name="pdf")
    assert "Traceback" not in message.content


def test_code_that_does_not_touch_the_snapshot_still_runs():
    called = []

    def enabled(skill_id: int) -> bool | None:
        raise AssertionError(f"lookup for {skill_id}")

    selection = _selection(enabled)

    def handler(request):
        called.append(request.tool_call["args"]["python_code"])
        return SimpleNamespace(content="ran")

    untouched = selection.wrap_tool_call(_code_request('open("uploads/a.md")'), handler)
    other = selection.wrap_tool_call(_code_request('open("skills/other/a.py")'), handler)
    assert untouched.content == "ran"
    assert other.content == "ran"
    assert called == ['open("uploads/a.md")', 'open("skills/other/a.py")']


def test_an_enabled_skill_can_still_be_executed():
    selection = _selection(_rows({PERSONAL_ID: True}))

    def handler(_request):
        return SimpleNamespace(content="ran")

    assert selection.wrap_tool_call(_code_request('open("skills/pdf/who.txt")'), handler).content == "ran"
