import pytest

from bisheng.common.errcode.permission import PermissionVersionConflictError
from bisheng.workflow.application.kunlian_workflow_authorization import AuthorizationError, GrantChange
from test.workflow.kunlian_workflow_authorization_fixtures import SOURCE_ID, WORKFLOW, PermissionFixture, direct_row


async def test_precise_grant_and_revoke_reuse_f048_mutation():
    fixture = PermissionFixture()
    service = fixture.service()
    fixture.rows = [direct_row(subject_type="user_group", assignee_id="40")]
    async with service._authorized(fixture.subject(), WORKFLOW, "manage_permission") as target:
        grant = GrantChange(3, 12, subject_ref="member-b", model_key="viewer")
        assert await service._submit_change(fixture.subject(), target, grant, "g") == 4
        assert fixture.last_change.op.value == "ADD"
        revoke = GrantChange(4, 12, assignee_id=SOURCE_ID, expected_assignee_version=1)
        assert await service._submit_change(fixture.subject(), target, revoke, "r") == 5
        assert fixture.last_change.assignee_id == SOURCE_ID
    assert [row["assignee_id"] for row in fixture.rows] == ["40"]


@pytest.mark.parametrize(
    "reason", ["other_tenant", "invalid_subject", "model", "resource_revision", "catalog_revision", "source_revision"]
)
async def test_change_refuses_invalid_scope_or_revisions(reason):
    fixture = PermissionFixture()
    fixture.rows = [direct_row()]
    grant = GrantChange(3, 12, subject_ref="member-b", model_key="viewer")
    if reason == "other_tenant":
        fixture.target_user = (8, 12)
    if reason == "invalid_subject":
        fixture.target_user = None
    if reason == "model":
        grant = GrantChange(3, 12, subject_ref="member-b", model_key="owner")
    if reason == "resource_revision":
        grant = GrantChange(2, 12, subject_ref="member-b", model_key="viewer")
    if reason == "catalog_revision":
        grant = GrantChange(3, 11, subject_ref="member-b", model_key="viewer")
    if reason == "source_revision":
        grant = GrantChange(3, 12, assignee_id=SOURCE_ID, expected_assignee_version=0)
    service = fixture.service()
    error = (
        AuthorizationError if reason in {"other_tenant", "invalid_subject", "model"} else PermissionVersionConflictError
    )
    async with service._authorized(fixture.subject(), WORKFLOW, "manage_permission") as target:
        with pytest.raises(error):
            await service._submit_change(fixture.subject(), target, grant, "unused")
    assert fixture.rows == [direct_row()] and fixture.mutations == 0
