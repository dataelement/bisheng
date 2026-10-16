"""F078 T35: workflow Open API events carry agent-node deliverables."""

from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.api.v1.schemas import ChatResponse


def _stream_end(files):
    return ChatResponse(
        category=WorkflowEventType.StreamMsg.value,
        type="end",
        chat_id="c1",
        flow_id="flow-1",
        message={"node_id": "agent_1", "name": "助手", "unique_id": "u1", "msg": "answer", "output_key": "output"},
        files=files,
    )


def test_stream_end_event_returns_deliverables_in_files():
    event = WorkFlowService.convert_chat_response_to_workflow_event(
        _stream_end(
            [
                {
                    "file_id": "f1",
                    "file_name": "周报.docx",
                    "object_name": "chat/7/agent/c1/f1.docx",
                    "bucket": "public",
                    "size": 12,
                    "file_url": "/api/v1/agent-runtime/files/c1/f1",
                }
            ]
        )
    )
    (file,) = event.output_schema.files
    assert file == {"file_id": "f1", "name": "周报.docx", "path": "/api/v2/workflow/files/c1/f1", "size": 12}
    # Internal storage details never reach the caller.
    assert "object_name" not in file
    assert event.output_schema.message == "answer"


def test_format_error_is_passed_through():
    event = WorkFlowService.convert_chat_response_to_workflow_event(
        _stream_end([{"file_id": "f1", "file_name": "a.pptx", "size": 1, "format_error": "not a zip"}])
    )
    assert event.output_schema.files[0]["format_error"] == "not a zip"


def test_no_deliverables_leaves_the_field_unset():
    event = WorkFlowService.convert_chat_response_to_workflow_event(_stream_end([]))
    assert event.output_schema.files is None
    assert event.output_schema.message == "answer"
