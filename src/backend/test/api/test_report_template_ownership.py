"""Issue #2190: a report template belongs to one workflow, and saving needs edit rights.

The template is a single stored object named after its ``version_key``, and that
key is visible to everyone who can open the workflow. Nothing used to tie the
key to a workflow, so naming someone else's key was enough to read, copy or
overwrite their template. Ownership now travels in the key itself -- renaming it
points at a different object -- so it cannot be forged through workflow data,
which the caller controls.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.api.services import report_template
from bisheng.api.v1 import workflow

WORKFLOW_A = "0013432d78ae4c54aac8459b010ed47e"
WORKFLOW_B = "002488f3de8e4761a3b05400f77b3fd9"
RANDOM = "11ea00ab245342799c8f03f2cd97e36e"
LEGACY_KEY = "0274a998b2d244c6aa54cf48c48ad45b"


def test_a_minted_key_names_its_workflow():
    key = report_template.mint_version_key(WORKFLOW_A)

    assert key.startswith(f"{WORKFLOW_A}-")
    assert report_template.owner_workflow_id(key) == WORKFLOW_A


def test_the_editor_timestamp_suffix_does_not_hide_the_owner():
    key = f"{WORKFLOW_A}-{RANDOM}_1789739207205"

    assert report_template.storage_key(key) == f"{WORKFLOW_A}-{RANDOM}"
    assert report_template.owner_workflow_id(key) == WORKFLOW_A


@pytest.mark.parametrize(
    "key",
    [
        LEGACY_KEY,  # minted before templates had an owner
        f"{LEGACY_KEY}_1789739207205",
        f"not-a-uuid-{RANDOM}",
        f"{WORKFLOW_A}-not-a-uuid",
        "",
        None,
    ],
)
def test_keys_without_a_readable_owner_report_none(key):
    assert report_template.owner_workflow_id(key) is None


def test_report_keys_are_read_out_of_flow_data():
    flow_data = {
        "nodes": [
            {"data": {"type": "llm", "group_params": []}},
            {
                "data": {
                    "type": "report",
                    "group_params": [
                        {
                            "params": [
                                {
                                    "key": "report_info",
                                    "value": {"file_name": "x", "version_key": f"{WORKFLOW_A}-{RANDOM}_17897"},
                                }
                            ]
                        }
                    ],
                }
            },
        ]
    }

    assert list(report_template.iter_report_keys(flow_data)) == [f"{WORKFLOW_A}-{RANDOM}"]


@pytest.fixture
def storage():
    minio = MagicMock()
    minio.bucket = "bisheng"
    minio.object_exists = AsyncMock(return_value=True)
    minio.get_share_link = AsyncMock(return_value="http://minio/x.docx")
    minio.copy_object = AsyncMock()
    minio.put_object = AsyncMock()
    return minio


@pytest.fixture
def report_env(monkeypatch, storage):
    """Wire the report endpoints to fakes: flow exists, storage is a mock."""
    monkeypatch.setattr(workflow.FlowDao, "aget_flow_by_id", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(workflow, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(report_template, "aremember_edit_session", AsyncMock())
    return storage


def _permissions(monkeypatch, *, visible: bool = True, edit: bool = True):
    async def check(login_user, *, resource_type, resource_id, action):
        return edit if action == "edit" else visible

    monkeypatch.setattr(workflow, "check_business_action", check)


async def test_reading_another_workflows_template_is_refused(monkeypatch, report_env):
    _permissions(monkeypatch)
    foreign_key = f"{WORKFLOW_B}-{RANDOM}"

    result = await workflow.get_report_file(
        MagicMock(),
        login_user=MagicMock(),
        version_key=foreign_key,
        workflow_id=WORKFLOW_A,
    )

    assert result.status_code != 200
    report_env.get_share_link.assert_not_called()


async def test_pasting_a_foreign_key_into_your_own_workflow_does_not_help(monkeypatch, report_env):
    """Workflow data is caller-controlled, so ownership is never read from it."""
    _permissions(monkeypatch, visible=True, edit=True)
    foreign_key = f"{WORKFLOW_B}-{RANDOM}"

    result = await workflow.get_report_file(
        MagicMock(),
        login_user=MagicMock(),
        version_key=foreign_key,
        workflow_id=WORKFLOW_A,
    )

    assert result.status_code != 200


async def test_reading_your_own_workflows_template_still_works(monkeypatch, report_env):
    _permissions(monkeypatch)
    own_key = f"{WORKFLOW_A}-{RANDOM}"

    result = await workflow.get_report_file(
        MagicMock(),
        login_user=MagicMock(),
        version_key=own_key,
        workflow_id=WORKFLOW_A,
    )

    assert result.data["url"] == "http://minio/x.docx"
    assert result.data["version_key"].startswith(f"{own_key}_")


async def test_a_new_template_is_minted_under_the_workflow(monkeypatch, report_env):
    _permissions(monkeypatch)

    result = await workflow.get_report_file(
        MagicMock(),
        login_user=MagicMock(),
        version_key="",
        workflow_id=WORKFLOW_A,
    )

    assert report_template.owner_workflow_id(result.data["version_key"]) == WORKFLOW_A


async def test_an_unowned_template_is_adopted_by_an_editor(monkeypatch, report_env):
    _permissions(monkeypatch, edit=True)
    # Nothing has been adopted yet: only the legacy document is in storage.
    report_env.object_exists = AsyncMock(side_effect=lambda bucket, name: name.endswith(f"{LEGACY_KEY}.docx"))

    result = await workflow.get_report_file(
        MagicMock(),
        login_user=MagicMock(),
        version_key=LEGACY_KEY,
        workflow_id=WORKFLOW_A,
    )

    adopted = result.data["version_key"]
    assert report_template.owner_workflow_id(adopted) == WORKFLOW_A
    # The stored document follows the key, otherwise the template would vanish.
    assert report_env.copy_object.call_args.kwargs["source_object"] == f"workflow/report/{LEGACY_KEY}.docx"


async def test_adopting_the_same_template_twice_lands_on_the_same_key(monkeypatch, report_env):
    """The node keeps the legacy key until the workflow is saved, so every open adopts again."""
    _permissions(monkeypatch, edit=True)

    first = await workflow.get_report_file(
        MagicMock(), login_user=MagicMock(), version_key=LEGACY_KEY, workflow_id=WORKFLOW_A
    )
    second = await workflow.get_report_file(
        MagicMock(), login_user=MagicMock(), version_key=LEGACY_KEY, workflow_id=WORKFLOW_A
    )

    assert report_template.storage_key(first.data["version_key"]) == report_template.storage_key(
        second.data["version_key"]
    )


async def test_re_opening_an_adopted_template_keeps_the_edits(monkeypatch, report_env):
    """Re-copying the legacy document would roll the template back to its old content."""
    _permissions(monkeypatch, edit=True)
    adopted = report_template.adopted_version_key(WORKFLOW_A, LEGACY_KEY)
    # The adopted object now exists: it was saved through the editor after the
    # first adoption, while the workflow itself was never saved.
    report_env.object_exists = AsyncMock(
        side_effect=lambda bucket, name: (
            name == f"workflow/report/{adopted}.docx" or name.endswith(f"{LEGACY_KEY}.docx")
        )
    )

    result = await workflow.get_report_file(
        MagicMock(), login_user=MagicMock(), version_key=LEGACY_KEY, workflow_id=WORKFLOW_A
    )

    assert result.data["version_key"].startswith(f"{adopted}_")
    report_env.copy_object.assert_not_called()


async def test_a_viewer_does_not_re_home_an_unowned_template(monkeypatch, report_env):
    _permissions(monkeypatch, visible=True, edit=False)

    result = await workflow.get_report_file(
        MagicMock(),
        login_user=MagicMock(),
        version_key=LEGACY_KEY,
        workflow_id=WORKFLOW_A,
    )

    assert result.data["version_key"].startswith(f"{LEGACY_KEY}_")
    report_env.copy_object.assert_not_called()


async def test_the_edit_session_records_whether_saving_is_allowed(monkeypatch, report_env):
    _permissions(monkeypatch, visible=True, edit=False)
    remember = AsyncMock()
    monkeypatch.setattr(report_template, "aremember_edit_session", remember)

    await workflow.get_report_file(
        MagicMock(),
        login_user=MagicMock(),
        version_key=f"{WORKFLOW_A}-{RANDOM}",
        workflow_id=WORKFLOW_A,
    )

    assert remember.call_args.kwargs["can_edit"] is False


@pytest.fixture
def callback_env(monkeypatch, storage):
    monkeypatch.setattr(workflow, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(workflow, "afetch_office_document", AsyncMock(return_value=b"docx"))
    return storage


async def _callback(key: str) -> dict:
    return await workflow.upload_report_file(
        MagicMock(),
        {"status": 6, "url": "http://office/cache/x.docx", "key": key},
    )


async def test_a_save_without_an_editor_session_is_refused(monkeypatch, callback_env):
    monkeypatch.setattr(report_template, "aget_edit_session", AsyncMock(return_value=None))

    assert await _callback(f"{WORKFLOW_B}-{RANDOM}") == {"error": 1}
    callback_env.put_object.assert_not_called()


async def test_a_viewer_save_is_refused(monkeypatch, callback_env):
    monkeypatch.setattr(
        report_template,
        "aget_edit_session",
        AsyncMock(return_value={"workflow_id": WORKFLOW_A, "can_edit": False}),
    )

    assert await _callback(f"{WORKFLOW_A}-{RANDOM}") == {"error": 1}
    callback_env.put_object.assert_not_called()


async def test_an_editor_save_is_stored(monkeypatch, callback_env):
    monkeypatch.setattr(
        report_template,
        "aget_edit_session",
        AsyncMock(return_value={"workflow_id": WORKFLOW_A, "can_edit": True}),
    )

    key = f"{WORKFLOW_A}-{RANDOM}"
    assert await _callback(f"{key}_1789739207205") == {"error": 0}
    assert callback_env.put_object.call_args.kwargs["object_name"] == f"workflow/report/{key}.docx"


async def test_copying_another_workflows_template_is_refused(monkeypatch, storage):
    monkeypatch.setattr(workflow, "get_minio_storage", AsyncMock(return_value=storage))
    _permissions(monkeypatch, visible=False)
    monkeypatch.setattr(report_template, "ais_app_template_asset", AsyncMock(return_value=False))

    result = await workflow.copy_report_file(
        MagicMock(),
        login_user=MagicMock(),
        version_key=f"{WORKFLOW_B}-{RANDOM}",
    )

    assert result.status_code != 200
    storage.copy_object.assert_not_called()


async def test_copying_a_published_app_template_is_allowed(monkeypatch, storage):
    """Starting an app from a template copies a node from a workflow you cannot see."""
    monkeypatch.setattr(workflow, "get_minio_storage", AsyncMock(return_value=storage))
    _permissions(monkeypatch, visible=False)
    monkeypatch.setattr(report_template, "ais_app_template_asset", AsyncMock(return_value=True))

    result = await workflow.copy_report_file(
        MagicMock(),
        login_user=MagicMock(),
        version_key=f"{WORKFLOW_B}-{RANDOM}",
    )

    assert result.data["version_key"]
    storage.copy_object.assert_called_once()


async def test_force_saving_someone_elses_template_is_refused(monkeypatch):
    monkeypatch.setattr(workflow.FlowDao, "aget_flow_by_id", AsyncMock(return_value=MagicMock()))
    _permissions(monkeypatch, edit=True)
    remember = AsyncMock()
    monkeypatch.setattr(report_template, "aremember_edit_session", remember)

    result = await workflow.force_save_report_file(
        MagicMock(),
        login_user=MagicMock(),
        workflow_id=WORKFLOW_A,
        version_key=f"{WORKFLOW_B}-{RANDOM}",
    )

    assert result.status_code != 200
    # Crucially it must not mint an edit session for the foreign key.
    remember.assert_not_called()


async def test_force_saving_an_unowned_template_is_refused(monkeypatch):
    """Otherwise a manual save mints an edit session for a legacy key and the
    callback then accepts an overwrite of somebody else's template."""
    monkeypatch.setattr(workflow.FlowDao, "aget_flow_by_id", AsyncMock(return_value=MagicMock()))
    _permissions(monkeypatch, edit=True)
    remember = AsyncMock()
    monkeypatch.setattr(report_template, "aremember_edit_session", remember)

    result = await workflow.force_save_report_file(
        MagicMock(),
        login_user=MagicMock(),
        workflow_id=WORKFLOW_A,
        version_key=LEGACY_KEY,
    )

    assert result.status_code != 200
    remember.assert_not_called()
