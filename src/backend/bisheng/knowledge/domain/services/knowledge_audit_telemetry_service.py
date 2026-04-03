from typing import List

from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.schemas.telemetry.event_data_schema import NewKnowledgeBaseEventData
from bisheng.common.services import telemetry_service
from bisheng.core.logger import trace_id_var
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.utils import get_request_ip


class KnowledgeAuditTelemetryService:
    """Centralized audit and telemetry operations for knowledge domain."""

    @staticmethod
    def audit_create_knowledge(login_user, request, knowledge: Knowledge) -> None:
        AuditLogService.create_knowledge(login_user, get_request_ip(request), knowledge.id)

    @staticmethod
    def telemetry_new_knowledge(login_user, knowledge: Knowledge) -> None:
        telemetry_service.log_event_sync(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.NEW_KNOWLEDGE_BASE,
            trace_id=trace_id_var.get(),
            event_data=NewKnowledgeBaseEventData(
                kb_id=knowledge.id,
                kb_name=knowledge.name,
                kb_type=knowledge.type,
            ),
        )

    @staticmethod
    def telemetry_delete_knowledge(login_user) -> None:
        telemetry_service.log_event_sync(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.DELETE_KNOWLEDGE_BASE,
            trace_id=trace_id_var.get(),
        )

    @staticmethod
    def audit_delete_knowledge(login_user, request, knowledge: Knowledge) -> None:
        AuditLogService.delete_knowledge(login_user, get_request_ip(request), knowledge)

    @staticmethod
    def audit_upload_knowledge_file(login_user, request, knowledge: Knowledge, file_list: List[KnowledgeFile]) -> None:
        file_name = ""
        for one in file_list:
            file_name += "\n\n" + one.file_name
        AuditLogService.upload_knowledge_file(
            login_user, get_request_ip(request), knowledge.id, file_name
        )

    @staticmethod
    def telemetry_new_knowledge_file(login_user) -> None:
        telemetry_service.log_event_sync(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.NEW_KNOWLEDGE_FILE,
            trace_id=trace_id_var.get(),
        )

    @staticmethod
    def telemetry_delete_knowledge_file(login_user) -> None:
        telemetry_service.log_event_sync(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.DELETE_KNOWLEDGE_FILE,
            trace_id=trace_id_var.get(),
        )

    @staticmethod
    def audit_delete_knowledge_file(login_user, request, knowledge_id: int, file_list: List[KnowledgeFile]) -> None:
        file_name = ""
        for one in file_list:
            file_name += "\n\n" + one.file_name
        AuditLogService.delete_knowledge_file(
            login_user, get_request_ip(request), knowledge_id, file_name
        )
