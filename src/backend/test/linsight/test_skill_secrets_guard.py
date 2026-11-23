"""F013: ``skills/<name>/secrets/`` is readable by executor code only.

E2E on 114 (2026-11-11) showed that whatever read_file returns is stored as step
output, which the UI and share links render (``execute-task-detail`` bypasses the
tenant filter for a share link). A password written in SKILL.md therefore reached
every viewer. Credentials now live under ``secrets/``; the workspace file tools
refuse it, while bisheng_code_interpreter reads the local disk directly.
"""

from unittest.mock import MagicMock

from deepagents.backends.protocol import LsResult

from bisheng.linsight.domain.services.workspace_backend import (
    SKILL_SECRET_ERROR_PREFIX,
    WORKSPACE_PREFIX,
    WorkspaceBackend,
    _is_skill_secret_path,
)

SECRET = "skills/shop-db/secrets/conn.json"
PASSWORD = "pw-should-never-surface"


def _backend(tmp_path) -> WorkspaceBackend:
    minio = MagicMock()
    minio.bucket = "bisheng"
    backend = WorkspaceBackend(svid="sv-secret", minio=minio, file_dir=str(tmp_path))
    backend._cache_write(SECRET, f'{{"password": "{PASSWORD}"}}'.encode())
    backend._cache_write("skills/shop-db/SKILL.md", b"# shop-db\nconnection: secrets/conn.json\n")
    return backend


def test_path_rule():
    assert _is_skill_secret_path(SECRET)
    assert _is_skill_secret_path("skills/x/secrets/nested/a.txt")
    assert not _is_skill_secret_path("skills/x/SKILL.md")
    assert not _is_skill_secret_path("skills/secrets/SKILL.md")  # a skill NAMED secrets
    assert not _is_skill_secret_path("scratch/secrets/a.txt")
    assert not _is_skill_secret_path("uploads/secrets/a.txt")


def test_read_refuses_and_routes_to_the_executor(tmp_path):
    result = _backend(tmp_path).read("/" + SECRET)
    assert result.file_data is None
    assert SKILL_SECRET_ERROR_PREFIX in result.error
    assert f'open("{SECRET}")' in result.error
    assert PASSWORD not in result.error


async def test_aread_refuses(tmp_path):
    result = await _backend(tmp_path).aread("/" + SECRET)
    assert result.file_data is None
    assert SKILL_SECRET_ERROR_PREFIX in result.error


def test_skill_md_stays_readable(tmp_path):
    result = _backend(tmp_path).read("/skills/shop-db/SKILL.md")
    assert result.error is None
    assert "secrets/conn.json" in result.file_data["content"]


def test_grep_never_scans_secrets(tmp_path):
    backend = _backend(tmp_path)
    prefix = f"/{WORKSPACE_PREFIX}/sv-secret/"
    backend.ls = lambda path="": LsResult(
        entries=[
            {"path": prefix + SECRET, "is_dir": False, "size": 40},
            {"path": prefix + "skills/shop-db/SKILL.md", "is_dir": False, "size": 40},
        ]
    )
    matches = backend.grep("password|connection").matches
    assert [m["path"] for m in matches] == [prefix + "skills/shop-db/SKILL.md"]
    assert all(PASSWORD not in m["text"] for m in matches)


def test_code_still_sees_the_file_on_local_disk(tmp_path):
    # The executor's cwd is file_dir; it never goes through the backend.
    _backend(tmp_path)
    assert PASSWORD in (tmp_path / SECRET).read_text()
