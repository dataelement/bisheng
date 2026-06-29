"""F038 — workflow input node file processing strategy (单选 + 输出变量联动).

Covers the normalization helpers (`_modes_for_file` / `_active_modes`) and the
unified variable-exposure rule (`_parse_upload_file_variables`):

    - file_path : always
    - image     : when file_type in {image, all}
    - content   : when extract_text is active
    - key       : when ingest_to_temp_kb is active

Accepted ``file_parse_mode`` shapes: dialog single string, form array
(`[extract]` / `[extract, ingest]` / `[keep_raw]`), plus legacy string and the
superseded per-type map (still tolerated). AC-01~AC-18.
"""

from bisheng.workflow.nodes.input.input import InputNode, ParseModeEnum

EXTRACT = ParseModeEnum.EXTRACT_TEXT.value
KEEP_RAW = ParseModeEnum.KEEP_RAW.value
INGEST = ParseModeEnum.INGEST_TO_KNOWLEDGE_BASE.value


# --- _modes_for_file: per-file mode resolution (AC-16) -----------------------


def test_modes_for_file_form_array():
    assert InputNode._modes_for_file([EXTRACT, INGEST], "doc") == {EXTRACT, INGEST}
    assert InputNode._modes_for_file([EXTRACT, ""], "doc") == {EXTRACT}


def test_modes_for_file_legacy_string():
    assert InputNode._modes_for_file(KEEP_RAW, "doc") == {KEEP_RAW}
    assert InputNode._modes_for_file(EXTRACT, "image") == {EXTRACT}


def test_modes_for_file_superseded_map_still_tolerated():
    # 上一版对话框 {doc,image} map — 仍能归一执行（兼容已部署 120 的节点）。
    mode = {"doc": EXTRACT, "image": KEEP_RAW}
    assert InputNode._modes_for_file(mode, "doc") == {EXTRACT}
    assert InputNode._modes_for_file(mode, "image") == {KEEP_RAW}


def test_modes_for_file_missing_defaults_to_ingest():
    # Legacy v2 form items predate file_parse_mode; default must stay ingest.
    assert InputNode._modes_for_file(None, "doc") == {INGEST}
    assert InputNode._modes_for_file("", "image") == {INGEST}


# --- _active_modes: union of configured modes (AC-16) ------------------------


def test_active_modes_form_combination():
    active, _ = InputNode._active_modes([EXTRACT, INGEST])
    assert active == {EXTRACT, INGEST}


def test_active_modes_legacy_string():
    active, _ = InputNode._active_modes(KEEP_RAW)
    assert active == {KEEP_RAW}


def test_active_modes_superseded_map():
    active, _ = InputNode._active_modes({"doc": EXTRACT, "image": KEEP_RAW})
    assert active == {EXTRACT, KEEP_RAW}


def test_active_modes_missing_defaults_to_ingest():
    active, _ = InputNode._active_modes(None)
    assert active == {INGEST}


# --- _parse_upload_file_variables: unified exposure rule ----------------------


def _make_node(v=3):
    """Build an InputNode without the heavy BaseNode __init__ for unit testing
    the pure variable-mapping logic."""
    node = InputNode.__new__(InputNode)
    node._current_v = 2
    node.node_data = type("_ND", (), {"v": v})()
    return node


def _key_info(file_type, file_parse_mode):
    return {
        "key": "k",
        "file_content": "c",
        "file_path": "p",
        "image_file": "img",
        "file_type": file_type,
        "file_parse_mode": file_parse_mode,
    }


_KEY_VALUE = {"c": "parsed text", "p": ["minio/p"], "img": ["minio/i"], "k": [{"document_name": "a"}]}


def _exposed(file_type, file_parse_mode):
    node = _make_node(v=3)
    return set(node._parse_upload_file_variables(_key_info(file_type, file_parse_mode), _KEY_VALUE))


# 对话框：策略 × 上传类型 矩阵（AC-01~AC-06）。'all'/'image'/'file'(=文档)
def test_dialog_extract_all_gives_content_image_path():
    assert _exposed("all", EXTRACT) == {"c", "img", "p"}


def test_dialog_extract_doc_gives_content_path_no_image():
    assert _exposed("file", EXTRACT) == {"c", "p"}


def test_dialog_extract_image_gives_content_image_path():
    assert _exposed("image", EXTRACT) == {"c", "img", "p"}


def test_dialog_keepraw_all_gives_image_path():
    assert _exposed("all", KEEP_RAW) == {"img", "p"}


def test_dialog_keepraw_doc_gives_path_only():
    assert _exposed("file", KEEP_RAW) == {"p"}


def test_dialog_keepraw_image_gives_image_path():
    assert _exposed("image", KEEP_RAW) == {"img", "p"}


# 表单：3 个固定组合 × 上传类型（AC-07~AC-14）
def test_form_parse_only_all():
    assert _exposed("all", [EXTRACT]) == {"c", "img", "p"}


def test_form_parse_only_doc():
    assert _exposed("file", [EXTRACT]) == {"c", "p"}


def test_form_parse_ingest_all_adds_key():
    assert _exposed("all", [EXTRACT, INGEST]) == {"c", "img", "p", "k"}


def test_form_parse_ingest_doc_adds_key_no_image():
    assert _exposed("file", [EXTRACT, INGEST]) == {"c", "p", "k"}


def test_form_keepraw_all():
    assert _exposed("all", [KEEP_RAW]) == {"img", "p"}


def test_form_keepraw_doc():
    assert _exposed("file", [KEEP_RAW]) == {"p"}


# 关键差异：解析也暴露 path+image（旧版 extract 只给 content）
def test_extract_now_also_exposes_path_and_image():
    exposed = _exposed("all", EXTRACT)
    assert "p" in exposed and "img" in exposed and "c" in exposed


# 历史值兼容
def test_legacy_string_extract_all():
    assert _exposed("all", EXTRACT) == {"c", "img", "p"}


def test_superseded_form_freeform_array_still_works():
    # 上一版表单自由多选 [extract, ingest, keep_raw] → 仍按统一规则暴露并集
    assert _exposed("all", [EXTRACT, INGEST, KEEP_RAW]) == {"c", "img", "p", "k"}


def test_legacy_v2_path_returns_value_untouched():
    node = _make_node(v=2)
    node.is_dialog_input = lambda: False
    ki = _key_info("all", INGEST)
    assert node._parse_upload_file_variables(ki, dict(_KEY_VALUE)) == _KEY_VALUE
