"""A parse failure is the uploader's business (and the managers'), nobody else's.

The rule used to live in the client's `file_status` query, which hid the row from the
uploader too and left the file reachable by anyone calling the API directly. It now sits
in `_filter_visible_child_items`, so the listing and the folder rollup — which reuses that
filter — agree.
"""

from types import SimpleNamespace

from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

SPACE_ID = 137
OWNER = 150025
OTHER = 150026


def _service(user_id, *, is_admin=False, can_manage=False):
    svc = object.__new__(KnowledgeSpaceService)
    svc.login_user = SimpleNamespace(user_id=user_id, tenant_id=1, is_admin=lambda: is_admin)

    async def _can_manage(uid, space_id):
        return can_manage

    svc._user_can_manage_space = _can_manage
    return svc


def _file(file_id, status, owner=OWNER):
    return KnowledgeFile(
        id=file_id,
        knowledge_id=SPACE_ID,
        file_type=FileType.FILE,
        file_level_path="/748",
        file_name=f"{file_id}.xlsx",
        status=status,
        user_id=owner,
    )


def _folder(folder_id=748):
    return KnowledgeFile(
        id=folder_id,
        knowledge_id=SPACE_ID,
        file_type=FileType.DIR,
        file_level_path="",
        file_name="folder",
        status=KnowledgeFileStatus.SUCCESS.value,
        user_id=OWNER,
    )


async def _visible(svc, items):
    kept = await svc._hide_others_failed_files(items, space_id=SPACE_ID)
    return {int(item.id) for item in kept}


async def test_another_members_failure_is_hidden():
    failed, ok = _file(1086, KnowledgeFileStatus.FAILED.value), _file(1085, KnowledgeFileStatus.SUCCESS.value)

    assert await _visible(_service(OTHER), [failed, ok]) == {1085}


async def test_the_uploader_sees_their_own_failure():
    failed = _file(1086, KnowledgeFileStatus.FAILED.value, owner=OWNER)

    assert await _visible(_service(OWNER), [failed]) == {1086}


async def test_admins_and_space_managers_see_every_failure():
    failed = _file(1086, KnowledgeFileStatus.FAILED.value)

    assert await _visible(_service(OTHER, is_admin=True), [failed]) == {1086}
    assert await _visible(_service(OTHER, can_manage=True), [failed]) == {1086}


async def test_timeout_and_violation_stay_visible_to_everyone():
    """Unchanged from the old client rule: only status 3 is the uploader's private business."""
    timeout = _file(1090, KnowledgeFileStatus.TIMEOUT.value)
    violation = _file(1091, KnowledgeFileStatus.VIOLATION.value)

    assert await _visible(_service(OTHER), [timeout, violation]) == {1090, 1091}


async def test_a_folder_is_never_hidden_by_the_rule():
    """Folders carry their own status; only files are judged here."""
    folder = _folder()
    folder.status = KnowledgeFileStatus.FAILED.value

    assert await _visible(_service(OTHER), [folder]) == {748}


async def test_no_failed_files_means_no_manage_lookup():
    svc = _service(OTHER)

    async def _boom(uid, space_id):
        raise AssertionError("manage permission must not be resolved when nothing failed")

    svc._user_can_manage_space = _boom

    assert await _visible(svc, [_file(1085, KnowledgeFileStatus.SUCCESS.value)]) == {1085}
