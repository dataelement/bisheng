import inspect

from bisheng.open_api.domain.scopes import OPEN_API_SCOPE_MAP
from bisheng.open_mcp.registry import SOURCE_ALLOWLIST

EXPECTED_API_ROUTES = {
    "create": ("POST", "/filelib/", 201),
    "update_knowledge": ("PUT", "/filelib/", 201),
    "get_knowledge": ("GET", "/filelib/", 200),
    "delete_knowledge_api": ("DELETE", "/filelib/{knowledge_id}", 200),
    "clear_knowledge_files": ("DELETE", "/filelib/clear/{knowledge_id}", 200),
    "retrieve_chunks": ("POST", "/filelib/retrieve", None),
    "upload_file": ("POST", "/filelib/file/{knowledge_id}", None),
    "get_filelist": ("GET", "/filelib/file/list", 200),
    "delete_knowledge_file": ("DELETE", "/filelib/file/{file_id}", 200),
    "delete_file_batch_api": ("POST", "/filelib/delete_file", 200),
}

EXPECTED_PARAMETERS = {
    "create": ("request", "knowledge", "version_repo", "doc_repo"),
    "update_knowledge": ("request", "knowledge", "version_repo", "doc_repo"),
    "get_knowledge": (
        "request",
        "knowledge_type",
        "name",
        "sort_by",
        "page_size",
        "cursor",
        "version_repo",
        "doc_repo",
    ),
    "delete_knowledge_api": ("request", "knowledge_id", "version_repo", "doc_repo"),
    "clear_knowledge_files": ("request", "knowledge_id", "version_repo", "doc_repo"),
    "retrieve_chunks": ("request", "req", "version_repo"),
    "upload_file": (
        "request",
        "knowledge_id",
        "split_mode",
        "separator",
        "separator_rule",
        "chunk_size",
        "chunk_overlap",
        "hierarchy_level",
        "append_title",
        "max_chunk_size",
        "callback_url",
        "file_url",
        "file",
        "background_tasks",
        "retain_images",
        "force_ocr",
        "enable_formula",
        "filter_page_header_footer",
        "excel_rule",
        "parent_id",
        "version_repo",
        "doc_repo",
    ),
    "get_filelist": (
        "request",
        "knowledge_id",
        "parent_id",
        "keyword",
        "status",
        "page_size",
        "cursor",
        "version_repo",
        "doc_repo",
    ),
    "delete_knowledge_file": ("request", "file_id"),
    "delete_file_batch_api": ("request", "file_ids"),
}


def test_source_allowlist_remains_a_subset_of_existing_open_api_routes():
    registered = {
        endpoint for code in ("knowledge:read", "knowledge:write") for endpoint in OPEN_API_SCOPE_MAP[code].endpoints
    }
    assert SOURCE_ALLOWLIST <= registered


def test_source_api_batch_delete_and_multipart_contract_remain_frozen():
    from bisheng.open_endpoints.api.endpoints.filelib import delete_file_batch_api, upload_file

    batch_annotation = delete_file_batch_api.__annotations__["file_ids"]
    assert batch_annotation == list[int]
    assert "file" in upload_file.__annotations__
    assert "file_url" in upload_file.__annotations__


def test_all_ten_source_routes_and_http_statuses_remain_frozen():
    from bisheng.open_endpoints.api.endpoints.filelib import router

    actual = {}
    for route in router.routes:
        name = getattr(route.endpoint, "__name__", "")
        if name in EXPECTED_API_ROUTES:
            actual[name] = (next(iter(route.methods)), route.path, route.status_code)
    assert actual == EXPECTED_API_ROUTES


def test_all_ten_source_endpoint_parameter_lists_remain_frozen():
    from bisheng.open_endpoints.api.endpoints import filelib

    actual = {
        name: tuple(inspect.signature(getattr(filelib, name)).parameters)
        for name in EXPECTED_PARAMETERS
    }
    assert actual == EXPECTED_PARAMETERS
