"""Workflow input node media file support (v3.0-beta1)."""

import pytest

from bisheng.common.errcode.flow import WorkflowMediaFileCountLimitError
from bisheng.workflow.nodes.input.input import InputNode, ParseModeEnum

EXTRACT = ParseModeEnum.EXTRACT_TEXT.value


def test_active_modes_media_only():
    active, keep_raw_flag = InputNode._active_modes({"media": EXTRACT})
    assert active == {EXTRACT}
    assert keep_raw_flag is False


def test_accepts_image_legacy_all():
    assert InputNode._accepts_image("all") is True


def test_accepts_image_array():
    assert InputNode._accepts_image(["image"]) is True
    assert InputNode._accepts_image(["file"]) is False


def test_parse_upload_variables_media_only_exposes_content():
    node = InputNode.__new__(InputNode)
    node._current_v = 2
    node.node_data = type("_ND", (), {"v": 3})()

    key_info = {
        "file_parse_mode": {"media": EXTRACT},
        "file_type": ["media"],
        "file_path": "dialog_file_paths",
        "image_file": "dialog_image_files",
        "file_content": "dialog_files_content",
        "key": "dialog_files",
    }
    key_value = {
        "dialog_file_paths": ["http://x/a.mp3"],
        "dialog_image_files": [],
        "dialog_files_content": "transcript",
        "dialog_files": [],
    }
    result = node._parse_upload_file_variables(key_info, key_value)
    assert "dialog_files_content" in result
    assert result["dialog_files_content"] == "transcript"
    assert "dialog_image_files" not in result


def test_count_media_files():
    urls = [
        "http://minio/bucket/abc123_recording.mp3",
        "http://minio/bucket/doc.pdf",
    ]
    # Without KnowledgeService mock, extension-based count still works on URL tail
    count = 0
    for url in urls:
        name = url.rsplit("/", 1)[-1]
        from bisheng.knowledge.domain.upload_file_size import is_media_filename

        if is_media_filename(name):
            count += 1
    assert count == 1


def test_media_count_limit_raises():
    node = InputNode.__new__(InputNode)
    node.id = "input_1"
    node.workflow_id = "wf"
    node.user_id = 1
    node.tenant_id = 1
    node._image_ext = ["png", "jpg", "jpeg", "bmp"]

    key_info = {
        "key": "dialog_files",
        "file_content": "dialog_files_content",
        "file_path": "dialog_file_paths",
        "image_file": "dialog_image_files",
        "file_parse_mode": EXTRACT,
        "file_content_size": 15000,
    }
    urls = [f"http://minio/f{i}.mp3" for i in range(6)]
    with pytest.raises(WorkflowMediaFileCountLimitError):
        node.parse_upload_file("dialog_files", key_info, urls)
