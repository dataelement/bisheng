"""F038 — workflow input node multi-select file parse mode.

Covers the normalization helpers (`_modes_for_file` / `_active_modes`) and the
variable-exposure logic (`_parse_upload_file_variables`) for the three accepted
shapes of ``file_parse_mode``: dialog per-type map, form mode array, and the
legacy single string. AC-10, AC-11, AC-13.
"""

from bisheng.workflow.nodes.input.input import InputNode, ParseModeEnum

EXTRACT = ParseModeEnum.EXTRACT_TEXT.value
KEEP_RAW = ParseModeEnum.KEEP_RAW.value
INGEST = ParseModeEnum.INGEST_TO_KNOWLEDGE_BASE.value


# --- _modes_for_file: per-file mode resolution (AC-10) -----------------------


def test_modes_for_file_dialog_map_by_kind():
    mode = {"doc": EXTRACT, "image": KEEP_RAW}
    assert InputNode._modes_for_file(mode, "doc") == {EXTRACT}
    assert InputNode._modes_for_file(mode, "image") == {KEEP_RAW}


def test_modes_for_file_dialog_map_missing_kind_is_empty():
    # 'all' dialog with only a doc group → an image file matches no group.
    assert InputNode._modes_for_file({"doc": EXTRACT}, "image") == set()


def test_modes_for_file_form_array():
    assert InputNode._modes_for_file([EXTRACT, INGEST], "doc") == {EXTRACT, INGEST}
    # empty entries are dropped
    assert InputNode._modes_for_file([EXTRACT, ""], "doc") == {EXTRACT}


def test_modes_for_file_legacy_string():
    assert InputNode._modes_for_file(KEEP_RAW, "doc") == {KEEP_RAW}


def test_modes_for_file_missing_defaults_to_ingest():
    # Legacy v2 form items predate file_parse_mode; default must stay ingest.
    assert InputNode._modes_for_file(None, "doc") == {INGEST}
    assert InputNode._modes_for_file("", "image") == {INGEST}


# --- _active_modes: union across groups + image keep_raw flag (AC-11) ---------


def test_active_modes_dialog_map_union_and_image_flag():
    active, image_keep_raw = InputNode._active_modes({"doc": EXTRACT, "image": KEEP_RAW})
    assert active == {EXTRACT, KEEP_RAW}
    assert image_keep_raw is True


def test_active_modes_dialog_map_no_image_group():
    active, image_keep_raw = InputNode._active_modes({"doc": KEEP_RAW})
    assert active == {KEEP_RAW}
    assert image_keep_raw is False


def test_active_modes_form_array_combination():
    active, image_keep_raw = InputNode._active_modes([EXTRACT, INGEST])
    assert active == {EXTRACT, INGEST}
    assert image_keep_raw is False


def test_active_modes_legacy_string_keep_raw():
    active, image_keep_raw = InputNode._active_modes(KEEP_RAW)
    assert active == {KEEP_RAW}
    assert image_keep_raw is True


def test_active_modes_missing_defaults_to_ingest():
    active, image_keep_raw = InputNode._active_modes(None)
    assert active == {INGEST}
    assert image_keep_raw is False


# --- _parse_upload_file_variables: which variables get exposed (AC-11/13) -----


def _make_node(v=3):
    """Build an InputNode without the heavy BaseNode __init__ for unit testing
    the pure variable-mapping logic."""
    node = InputNode.__new__(InputNode)
    node._current_v = 2
    node.node_data = type("_ND", (), {"v": v})()
    return node


_KEY_INFO_BASE = {
    "key": "k",
    "file_content": "c",
    "file_path": "p",
    "image_file": "img",
    "file_type": "all",
}
_KEY_VALUE = {"c": "parsed text", "p": ["minio/p"], "img": ["minio/i"], "k": [{"document_name": "a"}]}


def test_variables_form_extract_only():
    node = _make_node(v=3)
    key_info = {**_KEY_INFO_BASE, "file_parse_mode": [EXTRACT]}
    assert node._parse_upload_file_variables(key_info, _KEY_VALUE) == {"c": "parsed text"}


def test_variables_form_extract_plus_ingest_exposes_both():
    node = _make_node(v=3)
    key_info = {**_KEY_INFO_BASE, "file_parse_mode": [EXTRACT, INGEST]}
    ret = node._parse_upload_file_variables(key_info, _KEY_VALUE)
    assert set(ret) == {"c", "k"}


def test_variables_dialog_map_all_types_splits_doc_and_image():
    node = _make_node(v=3)
    # doc → extract (content), image → keep_raw (path + image var)
    key_info = {**_KEY_INFO_BASE, "file_parse_mode": {"doc": EXTRACT, "image": KEEP_RAW}}
    ret = node._parse_upload_file_variables(key_info, _KEY_VALUE)
    assert set(ret) == {"c", "p", "img"}


def test_variables_dialog_map_doc_keep_raw_no_image_var_when_doc_only():
    node = _make_node(v=3)
    key_info = {**_KEY_INFO_BASE, "file_type": "file", "file_parse_mode": {"doc": KEEP_RAW}}
    ret = node._parse_upload_file_variables(key_info, _KEY_VALUE)
    # keep_raw exposes path; image var withheld (no image group / doc-only type)
    assert set(ret) == {"p"}


def test_variables_legacy_string_extract_unchanged():
    node = _make_node(v=3)
    key_info = {**_KEY_INFO_BASE, "file_parse_mode": EXTRACT}
    assert node._parse_upload_file_variables(key_info, _KEY_VALUE) == {"c": "parsed text"}


def test_variables_legacy_v2_path_returns_value_untouched():
    # v <= _current_v keeps the old single-mode behavior; form input returns as-is.
    node = _make_node(v=2)
    node.is_dialog_input = lambda: False
    key_info = {**_KEY_INFO_BASE, "file_parse_mode": INGEST}
    assert node._parse_upload_file_variables(key_info, dict(_KEY_VALUE)) == _KEY_VALUE
