"""F086 T19: SubflowService keeps references in sync and runs the online, save and delete checks.

覆盖 AC: AC-03、AC-04、AC-05、AC-11、AC-12
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.flow import (
    WorkFlowReferencedDeleteError,
    WorkFlowSubflowNoPermissionError,
    WorkFlowSubflowNotFoundError,
    WorkFlowSubflowOnlineCheckError,
)
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.database.models.flow import FlowType
from bisheng.workflow.domain.services import subflow_service
from bisheng.workflow.domain.services.subflow_service import SubflowService
from test.workflow.subflow_helpers import chain, dialog_input, end, output, start, subflow_node


class FakeRefRepo:
    def __init__(self):
        self.rows: dict[str, list[str]] = {}

    async def replace_for_parent(self, parent_flow_id, child_flow_ids):
        self.rows[parent_flow_id] = list(dict.fromkeys(child_flow_ids))

    async def delete_for_parent(self, parent_flow_id):
        self.rows.pop(parent_flow_id, None)

    async def list_referrer_ids(self, child_flow_id):
        return [parent for parent, children in self.rows.items() if child_flow_id in children]

    async def list_child_ids(self, parent_flow_id):
        return list(self.rows.get(parent_flow_id, []))


class FakeFlows:
    def __init__(self):
        self.flows: dict[str, SimpleNamespace] = {}

    def add(self, flow_id, data, name="", flow_type=FlowType.WORKFLOW.value):
        self.flows[flow_id] = SimpleNamespace(
            id=flow_id, name=name or f"Flow {flow_id}", data=data, flow_type=flow_type
        )

    async def aget_flow_by_ids(self, flow_ids):
        return [self.flows[one] for one in flow_ids if one in self.flows]

    async def aget_flow_by_id(self, flow_id):
        return self.flows.get(flow_id)


@pytest.fixture
def repo():
    return FakeRefRepo()


@pytest.fixture
def flows():
    return FakeFlows()


@pytest.fixture(autouse=True)
def wiring(repo, flows):
    @asynccontextmanager
    async def ref_repo():
        yield repo

    with (
        patch.object(subflow_service, "_ref_repo", ref_repo),
        patch.object(subflow_service, "FlowDao", flows),
    ):
        yield


def _plain(*end_names: str, variables: list[dict] | None = None) -> dict:
    return chain(start(custom_variables=variables), end("end_c", dict.fromkeys(end_names, "start_c.current_time")))


def _parent_of(*child_ids: str) -> dict:
    return chain(
        start("start_p"), *[subflow_node(f"subflow_{i}", c) for i, c in enumerate(child_ids)], end("end_p", None)
    )


class TestSyncRefs:
    async def test_replaces_rows_with_current_children(self, repo):
        await SubflowService.sync_refs("parent", _parent_of("a", "b", "a"))
        assert repo.rows["parent"] == ["a", "b"]

        await SubflowService.sync_refs("parent", _parent_of("c"))
        assert repo.rows["parent"] == ["c"]

        await SubflowService.sync_refs("parent", _plain())
        assert repo.rows["parent"] == []

    async def test_self_reference_is_not_recorded(self, repo):
        await SubflowService.sync_refs("parent", _parent_of("parent", "a"))
        assert repo.rows["parent"] == ["a"]

    async def test_clear_refs_removes_the_parent(self, repo):
        await SubflowService.sync_refs("parent", _parent_of("a"))
        await SubflowService.clear_refs("parent")
        assert "parent" not in repo.rows


class TestCheckOnline:
    async def test_eligible_children_pass(self, flows):
        flows.add("a", _plain("x"))
        await SubflowService.check_online(_parent_of("a"))

    async def test_no_subflow_nodes_pass_without_queries(self):
        await SubflowService.check_online(_plain())

    @pytest.mark.parametrize(
        "child, bad_name, code",
        [
            (chain(start(), dialog_input("Ask"), end("end_c", None)), "Ask", "input_node"),
            (chain(start(), output("Pick", "choose"), end("end_c", None)), "Pick", "interactive_output_node"),
            (chain(start(), subflow_node("Inner", "zzz"), end("end_c", None)), "Inner", "subflow_node"),
        ],
    )
    async def test_child_with_forbidden_node_is_rejected(self, flows, child, bad_name, code):
        flows.add("a", child, name="Child A")
        with pytest.raises(WorkFlowSubflowOnlineCheckError) as raised:
            await SubflowService.check_online(_parent_of("a"))
        assert raised.value.kwargs["subflow_name"] == "Child A"
        assert raised.value.kwargs["reasons"] == bad_name
        assert raised.value.kwargs["reason_codes"] == [code]

    async def test_reserved_return_name_is_rejected(self, flows):
        flows.add("a", _plain("chat_history"), name="Child A")
        with pytest.raises(WorkFlowSubflowOnlineCheckError) as raised:
            await SubflowService.check_online(_parent_of("a"))
        assert raised.value.kwargs["reasons"] == "chat_history"

    async def test_deleted_child_is_rejected(self):
        with pytest.raises(WorkFlowSubflowNotFoundError):
            await SubflowService.check_online(_parent_of("gone"))

    async def test_child_that_is_not_a_workflow_is_rejected(self, flows):
        flows.add("a", _plain("x"), flow_type=FlowType.ASSISTANT.value)
        with pytest.raises(WorkFlowSubflowNotFoundError):
            await SubflowService.check_online(_parent_of("a"))


class TestCheckNewRefs:
    """R-5.1 holds only if whoever adds a reference can edit the child; AC-10 keeps old ones."""

    @pytest.fixture
    def allowed(self):
        allowed = {"mine"}

        async def check(login_user, *, resource_type, resource_id, action):
            assert (resource_type, action) == ("workflow", "edit")
            checked.append(resource_id)
            return resource_id in allowed

        checked: list[str] = []
        with patch.object(subflow_service, "check_business_action", check):
            yield checked

    async def test_new_reference_without_edit_permission_is_rejected(self, allowed):
        with pytest.raises(WorkFlowSubflowNoPermissionError) as raised:
            await SubflowService.check_new_refs("user", "parent", _parent_of("mine", "theirs"))
        assert raised.value.kwargs == {"subflow_name": "snapshot theirs"}
        assert allowed == ["mine", "theirs"]

    async def test_editable_new_reference_passes(self, allowed):
        await SubflowService.check_new_refs("user", "parent", _parent_of("mine"))
        assert allowed == ["mine"]

    async def test_recorded_reference_is_not_checked_again(self, repo, allowed):
        repo.rows["parent"] = ["theirs"]
        await SubflowService.check_new_refs("user", "parent", _parent_of("theirs"))
        assert allowed == []

    async def test_reference_in_the_replaced_data_is_not_checked_again(self, allowed):
        await SubflowService.check_new_refs("user", "parent", _parent_of("theirs"), _parent_of("theirs"))
        assert allowed == []

    async def test_new_workflow_checks_every_reference(self, allowed):
        with pytest.raises(WorkFlowSubflowNoPermissionError):
            await SubflowService.check_new_refs("user", None, _parent_of("theirs"))

    async def test_self_reference_and_plain_data_skip_the_check(self, allowed):
        await SubflowService.check_new_refs("user", "parent", _parent_of("parent"))
        await SubflowService.check_new_refs("user", "parent", None)
        assert allowed == []


class TestSaveWarning:
    async def test_no_warning_when_not_referenced(self):
        warning = await SubflowService.build_save_warning(
            "child", _plain("a"), chain(start(), dialog_input("Ask"), end("end_c", None))
        )
        assert warning is None

    async def test_no_warning_when_nothing_relevant_changed(self, repo, flows):
        flows.add("p1", {}, name="Parent 1")
        repo.rows["p1"] = ["child"]
        assert await SubflowService.build_save_warning("child", _plain("a"), _plain("a")) is None

    async def test_forbidden_nodes_are_reported_with_referrers(self, repo, flows):
        flows.add("p1", {}, name="Parent 1")
        flows.add("p2", {}, name="Parent 2")
        repo.rows.update({"p1": ["child"], "p2": ["child"], "p3": ["child"]})  # p3 no longer exists

        warning = await SubflowService.build_save_warning(
            "child", _plain("a"), chain(start(), dialog_input("Ask"), end("end_c", {"a": "start_c.current_time"}))
        )

        assert warning["referenced_by"] == [{"id": "p1", "name": "Parent 1"}, {"id": "p2", "name": "Parent 2"}]
        assert warning["forbidden_nodes"] == [{"id": "Ask", "name": "Ask", "type": "input"}]
        assert warning["interface_changes"] == {
            "inputs_added": [],
            "inputs_removed": [],
            "outputs_added": [],
            "outputs_removed": [],
        }

    async def test_interface_changes_are_reported(self, repo, flows):
        flows.add("p1", {}, name="Parent 1")
        repo.rows["p1"] = ["child"]
        old = _plain(
            "a", "b", variables=[{"key": "1", "label": "x", "value": ""}, {"key": "2", "label": "y", "value": ""}]
        )
        new = _plain(
            "b",
            "c",
            variables=[{"key": "1", "label": "x", "value": "changed"}, {"key": "3", "label": "z", "value": ""}],
        )

        warning = await SubflowService.build_save_warning("child", old, new)

        assert warning["forbidden_nodes"] == []
        assert warning["interface_changes"] == {
            "inputs_added": ["z"],
            "inputs_removed": ["y"],
            "outputs_added": ["c"],
            "outputs_removed": ["a"],
        }


class TestCheckDelete:
    async def test_referenced_workflow_cannot_be_deleted(self, repo, flows):
        flows.add("p1", {}, name="Parent 1")
        flows.add("p2", {}, name="Parent 2")
        repo.rows.update({"p1": ["child"], "p2": ["child", "other"]})

        with pytest.raises(WorkFlowReferencedDeleteError) as raised:
            await SubflowService.check_delete("child")
        assert raised.value.kwargs["referenced_by"] == "Parent 1, Parent 2"
        assert raised.value.kwargs["referrers"] == [{"id": "p1", "name": "Parent 1"}, {"id": "p2", "name": "Parent 2"}]

    async def test_unreferenced_workflow_can_be_deleted(self, repo, flows):
        repo.rows["p_gone"] = ["child"]  # the referrer itself no longer exists
        await SubflowService.check_delete("child")
        await SubflowService.check_delete("never_used")


class TestFilterCandidates:
    async def test_keeps_only_eligible_rows_except_self(self, flows):
        flows.add("ok", _plain("a"))
        flows.add("self", _plain("a"))
        flows.add("input", chain(start(), dialog_input("Ask"), end("end_c", None)))
        flows.add("choose", chain(start(), output("Pick", "choose"), end("end_c", None)))
        flows.add("nested", _parent_of("ok"))
        rows = [{"id": one, "name": one, "description": "d", "logo": "l", "extra": 1} for one in flows.flows]
        rows.append({"id": "vanished", "name": "vanished"})

        result = await SubflowService.filter_candidates(rows, exclude_flow_id="self")

        assert result == [{"id": "ok", "name": "ok", "description": "d", "logo": "l"}]

    async def test_empty_page(self):
        assert await SubflowService.filter_candidates([], exclude_flow_id=None) == []


class TestGetInterface:
    async def test_returns_inputs_outputs_and_eligibility(self, flows):
        flows.add(
            "a",
            chain(
                start(custom_variables=[{"key": "1", "label": "city", "value": "SH"}]),
                dialog_input("Ask"),
                end("end_c", {"answer": "start_c.current_time"}),
            ),
            name="Child A",
        )
        check = AsyncMock()
        with patch.object(subflow_service, "require_business_action", check):
            result = await SubflowService.get_interface("user", "a")

        check.assert_awaited_once_with("user", resource_type="workflow", resource_id="a", action="edit")
        assert result == {
            "id": "a",
            "name": "Child A",
            "inputs": [{"name": "city", "value": "SH"}],
            "outputs": ["answer"],
            "eligible": False,
            "ineligible_reasons": ["input_node"],
        }

    async def test_missing_or_non_workflow_is_not_found(self, flows):
        flows.add("assistant", {}, flow_type=FlowType.ASSISTANT.value)
        with patch.object(subflow_service, "require_business_action", AsyncMock()):
            for flow_id in ("gone", "assistant"):
                with pytest.raises(NotFoundError):
                    await SubflowService.get_interface("user", flow_id)

    async def test_permission_denied_propagates(self, flows):
        flows.add("a", _plain())
        with (
            patch.object(subflow_service, "require_business_action", AsyncMock(side_effect=PermissionError)),
            pytest.raises(PermissionError),
        ):
            await SubflowService.get_interface("user", "a")
