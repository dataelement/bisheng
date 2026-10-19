"""F086 T24: every Flow.data write entry and both online entries call SubflowService, in order.

The entries are called directly with their collaborators mocked. Real HTTP,
permission filtering with a non-admin account and the MySQL table are
covered by the E2E run (T34); see tasks.md "测试降级".

覆盖 AC: AC-03、AC-04、AC-05、AC-11、AC-12
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.api.services import flow as flow_service_module
from bisheng.api.services import workflow as workflow_service_module
from bisheng.api.v1 import flows as flows_api
from bisheng.api.v1 import workflow as workflow_api
from bisheng.common.errcode.flow import WorkFlowReferencedDeleteError, WorkFlowSubflowOnlineCheckError
from bisheng.database.models.flow import FlowStatus, FlowType


class Calls:
    """Shared call log so tests can assert the order across collaborators."""

    def __init__(self):
        self.log: list[tuple] = []

    def async_mock(self, name: str, result=None, error: Exception | None = None) -> AsyncMock:
        async def _call(*args, **kwargs):
            self.log.append((name, *args))
            if error is not None:
                raise error
            return result

        return AsyncMock(side_effect=_call)

    def sync_mock(self, name: str, result=None) -> MagicMock:
        def _call(*args, **kwargs):
            self.log.append((name, *args))
            return result

        return MagicMock(side_effect=_call)

    def names(self) -> list[str]:
        return [one[0] for one in self.log]


@pytest.fixture
def calls():
    return Calls()


def _subflow_service(calls: Calls, **errors) -> SimpleNamespace:
    return SimpleNamespace(
        sync_refs=calls.async_mock("sync_refs"),
        clear_refs=calls.async_mock("clear_refs"),
        check_online=calls.async_mock("check_online", error=errors.get("check_online")),
        check_delete=calls.async_mock("check_delete", error=errors.get("check_delete")),
        build_save_warning=calls.async_mock("build_save_warning", result=errors.get("warning")),
    )


USER = SimpleNamespace(user_id=1, tenant_id=1)


class TestDelete:
    async def _delete(self, calls, service):
        flow = SimpleNamespace(id="child", name="Child", data={})
        flow_service = SimpleNamespace(
            project_flow_delete=calls.async_mock("project_flow_delete"),
            delete_flow_hook=calls.sync_mock("delete_flow_hook"),
        )
        flow_dao = SimpleNamespace(
            get_flow_by_id=MagicMock(return_value=flow), delete_flow=calls.sync_mock("delete_flow")
        )
        with (
            patch.object(flows_api, "SubflowService", service),
            patch.object(flows_api, "FlowService", flow_service),
            patch.object(flows_api, "FlowDao", flow_dao),
            patch.object(flows_api, "telemetry_service", MagicMock()),
        ):
            return await flows_api.delete_flow(request=MagicMock(), flow_id="child", login_user=USER)

    async def test_referenced_workflow_is_refused_before_permission_projection(self, calls):
        service = _subflow_service(calls, check_delete=WorkFlowReferencedDeleteError(referenced_by="Parent"))
        with pytest.raises(WorkFlowReferencedDeleteError):
            await self._delete(calls, service)
        assert calls.names() == ["check_delete"]

    async def test_delete_clears_own_references_after_the_row_is_gone(self, calls):
        await self._delete(calls, _subflow_service(calls))
        assert calls.names() == ["check_delete", "project_flow_delete", "delete_flow", "clear_refs", "delete_flow_hook"]
        assert ("clear_refs", "child") in calls.log


class TestAppListOnline:
    async def _update(self, calls, service, current_status, payload):
        db_flow = SimpleNamespace(id="parent", status=current_status, data={"nodes": ["parent data"]}, logo="")
        flow_dao = SimpleNamespace(
            aget_flow_by_id=AsyncMock(return_value=db_flow), aupdate_flow=calls.async_mock("aupdate_flow", db_flow)
        )
        with (
            patch.object(workflow_api, "SubflowService", service),
            patch.object(workflow_api, "FlowDao", flow_dao),
            patch.object(workflow_api, "check_business_action", AsyncMock(return_value=True)),
            patch.object(workflow_api, "telemetry_service", MagicMock(log_event=AsyncMock())),
            patch.object(workflow_api, "FlowService", SimpleNamespace(update_flow_hook=AsyncMock())),
        ):
            flow = workflow_api.FlowUpdate(**payload)
            return await workflow_api.update_flow(request=MagicMock(), flow_id="parent", flow=flow, login_user=USER)

    async def test_going_online_checks_the_current_data(self, calls):
        await self._update(
            calls, _subflow_service(calls), FlowStatus.OFFLINE.value, {"status": FlowStatus.ONLINE.value}
        )
        assert calls.log[0] == ("check_online", {"nodes": ["parent data"]})
        assert calls.names() == ["check_online", "aupdate_flow"]

    async def test_rejected_online_does_not_write(self, calls):
        service = _subflow_service(calls, check_online=WorkFlowSubflowOnlineCheckError(subflow_name="C", reasons="Ask"))
        with pytest.raises(WorkFlowSubflowOnlineCheckError):
            await self._update(calls, service, FlowStatus.OFFLINE.value, {"status": FlowStatus.ONLINE.value})
        assert calls.names() == ["check_online"]

    async def test_other_updates_skip_the_check(self, calls):
        await self._update(
            calls, _subflow_service(calls), FlowStatus.ONLINE.value, {"status": FlowStatus.OFFLINE.value}
        )
        await self._update(calls, _subflow_service(calls), FlowStatus.OFFLINE.value, {"name": "renamed"})
        assert "check_online" not in calls.names()


class TestEditPageOnline:
    async def _online(self, calls, service, status=FlowStatus.ONLINE.value):
        db_flow = SimpleNamespace(id="parent", name="Parent", status=FlowStatus.OFFLINE.value)
        version = SimpleNamespace(id=3, flow_id="parent", data={"nodes": ["version data"]})
        with (
            patch.object(workflow_service_module, "SubflowService", service),
            patch.object(
                workflow_service_module,
                "FlowDao",
                SimpleNamespace(
                    aget_flow_by_id=AsyncMock(return_value=db_flow), aupdate_flow=calls.async_mock("aupdate_flow")
                ),
            ),
            patch.object(
                workflow_service_module,
                "FlowVersionDao",
                SimpleNamespace(
                    aget_version_by_id=AsyncMock(return_value=version),
                    change_current_version=calls.async_mock("change_current_version"),
                ),
            ),
            patch.object(workflow_service_module, "require_business_action", AsyncMock()),
            patch.object(workflow_service_module, "Workflow", MagicMock()),
            patch.object(workflow_service_module, "telemetry_service", MagicMock(log_event=AsyncMock())),
        ):
            await workflow_service_module.WorkFlowService.update_flow_status(USER, "parent", 3, status)

    async def test_checks_the_version_going_online_then_syncs(self, calls):
        await self._online(calls, _subflow_service(calls))
        assert calls.names() == ["check_online", "change_current_version", "sync_refs", "aupdate_flow"]
        assert calls.log[0] == ("check_online", {"nodes": ["version data"]})
        assert calls.log[2] == ("sync_refs", "parent", {"nodes": ["version data"]})

    async def test_rejected_online_keeps_the_current_version(self, calls):
        service = _subflow_service(calls, check_online=WorkFlowSubflowOnlineCheckError(subflow_name="C", reasons="Ask"))
        with pytest.raises(WorkFlowSubflowOnlineCheckError):
            await self._online(calls, service)
        assert calls.names() == ["check_online"]

    async def test_going_offline_skips_the_check(self, calls):
        await self._online(calls, _subflow_service(calls), status=FlowStatus.OFFLINE.value)
        assert calls.names() == ["aupdate_flow"]


WARNING = {"referenced_by": [{"id": "p1", "name": "P1"}], "forbidden_nodes": [], "interface_changes": {}}


class TestSaveVersion:
    async def _save(self, calls, service, is_current: int, new_data):
        version = flow_service_module.FlowVersion(
            id=9, flow_id="child", name="v1", data={"old": True}, is_current=is_current, is_delete=0, user_id=1
        )
        flow_info = SimpleNamespace(id="child", status=FlowStatus.OFFLINE.value)

        async def aupdate(one):
            calls.log.append(("aupdate_version", dict(one.data)))
            return one

        with (
            patch.object(flow_service_module, "SubflowService", service),
            patch.object(flow_service_module.FlowVersionDao, "aget_version_by_id", AsyncMock(return_value=version)),
            patch.object(flow_service_module.FlowVersionDao, "aupdate_version", AsyncMock(side_effect=aupdate)),
            patch.object(
                flow_service_module.FlowService, "judge_flow_write_permission", AsyncMock(return_value=flow_info)
            ),
            patch.object(flow_service_module.FlowService, "update_flow_hook", AsyncMock()),
            patch.object(flow_service_module, "telemetry_service", MagicMock(log_event=AsyncMock())),
        ):
            payload = flow_service_module.FlowVersionCreate(name="v1", data=new_data, flow_type=FlowType.WORKFLOW.value)
            return await flow_service_module.FlowService.update_version_info(MagicMock(), USER, 9, payload)

    async def test_current_version_syncs_and_compares_with_the_data_before_saving(self, calls):
        resp = await self._save(calls, _subflow_service(calls, warning=WARNING), 1, {"new": True})
        assert calls.names() == ["aupdate_version", "sync_refs", "build_save_warning"]
        assert calls.log[2] == ("build_save_warning", "child", {"old": True}, {"new": True})
        assert resp.data["subflow_warning"] == WARNING
        assert resp.data["id"] == 9

    async def test_no_warning_keeps_the_old_response(self, calls):
        resp = await self._save(calls, _subflow_service(calls), 1, {"new": True})
        assert isinstance(resp.data, flow_service_module.FlowVersion)

    async def test_other_versions_are_not_synced(self, calls):
        await self._save(calls, _subflow_service(calls, warning=WARNING), 0, {"new": True})
        assert calls.names() == ["aupdate_version"]


class TestChangeVersion:
    async def test_compares_with_the_flow_data_before_switching(self, calls):
        flow_info = SimpleNamespace(id="child", status=FlowStatus.OFFLINE.value, data={"old": True})
        version = SimpleNamespace(id=4, flow_id="child", is_current=0, data={"new": True})
        with (
            patch.object(flow_service_module, "SubflowService", _subflow_service(calls, warning=WARNING)),
            patch.object(flow_service_module.FlowVersionDao, "aget_version_by_id", AsyncMock(return_value=version)),
            patch.object(
                flow_service_module.FlowVersionDao, "change_current_version", calls.async_mock("change", True)
            ),
            patch.object(
                flow_service_module.FlowService, "judge_flow_write_permission", AsyncMock(return_value=flow_info)
            ),
            patch.object(flow_service_module.FlowService, "update_flow_hook", AsyncMock()),
            patch.object(flow_service_module, "telemetry_service", MagicMock(log_event=AsyncMock())),
        ):
            resp = await flow_service_module.FlowService.change_current_version(MagicMock(), USER, "child", 4)

        assert calls.names() == ["change", "sync_refs", "build_save_warning"]
        assert calls.log[1] == ("sync_refs", "child", {"new": True})
        assert calls.log[2] == ("build_save_warning", "child", {"old": True}, {"new": True})
        assert resp.data == {"subflow_warning": WARNING}


class TestCreate:
    async def test_new_workflow_records_its_subflows(self, calls):
        created = SimpleNamespace(id="new", data={"nodes": ["copied"], "edges": []})
        session = MagicMock()
        session.__enter__.return_value.exec.return_value.first.return_value = None
        flow = workflow_api.FlowCreate(name="Copy", data={"nodes": ["copied"], "edges": []})
        with (
            patch.object(workflow_api, "SubflowService", _subflow_service(calls)),
            patch.object(workflow_api, "get_sync_db_session", MagicMock(return_value=session)),
            patch.object(workflow_api.Flow, "model_validate", MagicMock(return_value=SimpleNamespace())),
            patch.object(workflow_api, "FlowDao", SimpleNamespace(create_flow=MagicMock(return_value=created))),
            patch.object(
                workflow_api,
                "FlowVersionDao",
                SimpleNamespace(get_version_by_flow=MagicMock(return_value=SimpleNamespace(id=1))),
            ),
            patch.object(
                workflow_api, "FlowRead", SimpleNamespace(model_validate=MagicMock(return_value=SimpleNamespace()))
            ),
            patch.object(workflow_api, "FlowService", SimpleNamespace(create_flow_hook=AsyncMock())),
        ):
            await workflow_api.create_flow.__wrapped__(request=MagicMock(), flow=flow, login_user=USER)
        assert calls.log == [("sync_refs", "new", {"nodes": ["copied"], "edges": []})]


def _page(ids: list[str], next_cursor: str | None):
    rows = [{"id": one, "name": one, "description": "", "logo": ""} for one in ids]
    return SimpleNamespace(data=rows, has_more=next_cursor is not None, next_cursor=next_cursor)


class TestCandidates:
    async def _list(self, pages: list, eligible: set[str], page_size: int):
        envelope = AsyncMock(side_effect=pages)

        async def keep(rows, exclude_flow_id):
            return [row for row in rows if row["id"] in eligible and row["id"] != exclude_flow_id]

        service = SimpleNamespace(filter_candidates=AsyncMock(side_effect=keep))
        with (
            patch.object(workflow_api.WorkFlowService, "get_all_flows_envelope", envelope),
            patch.object(workflow_api, "SubflowService", service),
        ):
            resp = await workflow_api.list_subflow_candidates(
                login_user=USER, name="x", cursor=None, page_size=page_size, exclude_flow_id="self"
            )
        return resp.data, envelope

    async def test_scans_more_pages_until_the_page_is_full(self):
        pages = [_page(["a", "self"], "c1"), _page(["bad"], "c2"), _page(["b", "c"], "c3"), _page(["d"], None)]
        data, envelope = await self._list(pages, {"a", "b", "c", "d", "self"}, page_size=3)
        assert [one["id"] for one in data["data"]] == ["a", "b", "c"]
        assert data["cursor"] == "c3"
        assert envelope.await_count == 3
        first = envelope.await_args_list[0]
        assert first.args[4] == FlowType.WORKFLOW.value
        assert first.kwargs["managed"] is True
        assert envelope.await_args_list[1].kwargs["cursor"] == "c1"

    async def test_stops_after_five_pages(self):
        pages = [_page([f"bad{i}"], f"c{i}") for i in range(10)]
        data, envelope = await self._list(pages, set(), page_size=3)
        assert envelope.await_count == 5
        assert data == {"data": [], "cursor": "c4"}

    async def test_last_page_returns_no_cursor(self):
        data, _ = await self._list([_page(["a"], None)], {"a"}, page_size=3)
        assert data == {"data": [{"id": "a", "name": "a", "description": "", "logo": ""}], "cursor": None}


async def test_interface_endpoint_passes_the_user_through():
    service = SimpleNamespace(get_interface=AsyncMock(return_value={"id": "a"}))
    with patch.object(workflow_api, "SubflowService", service):
        resp = await workflow_api.get_subflow_interface(flow_id="a", login_user=USER)
    service.get_interface.assert_awaited_once_with(USER, "a")
    assert resp.data == {"id": "a"}
