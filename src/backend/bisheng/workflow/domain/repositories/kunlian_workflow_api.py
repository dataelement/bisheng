"""昆联工作流元数据写入的窄仓储; 不处理发布状态。"""

from bisheng.common.errcode.flow import WorkflowRegistrationConflict, WorkflowRegistrationDenied
from bisheng.database.models.flow import FlowStatus
from bisheng.workflow.domain.repositories.kunlian_registration import version_revision
from bisheng.workflow.domain.repositories.platform_agent import PlatformAgentRepository


class KunlianWorkflowMetadataRepository(PlatformAgentRepository):
    def _locked_pair(self, session, workflow_id, tenant_id, version_id):
        flow = self._flow(session, workflow_id, lock=True)
        if flow.tenant_id != tenant_id or flow.flow_type != 10:
            raise WorkflowRegistrationDenied()
        version = self._version(session, version_id, lock=True)
        if version.flow_id != workflow_id or version.tenant_id != tenant_id:
            raise WorkflowRegistrationConflict()
        return flow, version

    def save_draft(self, workflow_id, tenant_id, version_id, revision, *, name=None, description=None, data=None):
        with self.transaction() as session:
            flow, version = self._locked_pair(session, workflow_id, tenant_id, version_id)
            if (
                (flow.status == FlowStatus.ONLINE.value and version.is_current)
                or not revision
                or revision != version_revision(version)
            ):
                raise WorkflowRegistrationConflict()
            if name is not None:
                version.name = name
            if description is not None:
                version.description = description
            if data is not None:
                from bisheng.workflow.domain.schemas.kunlian_redaction import merge_redacted_workflow_secrets

                version.data = self.candidate_graph(merge_redacted_workflow_secrets(data, version.data))
                if version.is_current:
                    flow.data = version.data
            session.add(version)
            session.flush()
            return {**version.model_dump(), "draft_revision": version_revision(version)}

    def unpublish(self, workflow_id, tenant_id, version_id):
        with self.transaction() as session:
            flow, version = self._locked_pair(session, workflow_id, tenant_id, version_id)
            if version.is_current != 1:
                raise WorkflowRegistrationConflict()
            flow.status = FlowStatus.OFFLINE.value
            session.add(flow)

    def update_metadata(self, workflow_id, tenant_id, values):
        with self.transaction() as session:
            flow = self._flow(session, workflow_id, lock=True)
            if flow.tenant_id != tenant_id or flow.flow_type != 10:
                raise WorkflowRegistrationDenied()
            if flow.status == FlowStatus.ONLINE.value:
                raise WorkflowRegistrationConflict()
            for name, value in values.items():
                if name not in {"name", "description", "logo"}:
                    raise WorkflowRegistrationDenied()
                setattr(flow, name, value)
            session.add(flow)
            session.flush()
            return {
                name: getattr(flow, name)
                for name in ("id", "name", "description", "logo", "status", "create_time", "update_time")
                if hasattr(flow, name)
            }
