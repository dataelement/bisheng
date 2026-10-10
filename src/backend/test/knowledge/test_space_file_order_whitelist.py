"""F072: ``order_field`` / ``order_sort`` reach ``ORDER BY`` as raw SQL text.

Both the space children/search endpoints (typed query params → 422) and the DAO
(``ValueError``) must refuse anything outside the whitelist.
"""

import ast
from pathlib import Path

import pytest

from bisheng.knowledge.domain.models.knowledge_space_file import (
    SpaceFileDao,
    SpaceFileOrderField,
    SpaceFileOrderSort,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "bisheng"


@pytest.mark.parametrize("field", ["file_type", "file_name", "file_size", "update_time", "create_time"])
@pytest.mark.parametrize("sort", ["asc", "desc", "ASC", "DESC"])
def test_whitelisted_values_render(field, sort):
    text = SpaceFileDao.order_field_text(field, sort)
    assert sort.upper() in text
    if field != "file_type":
        assert text.startswith(f"{field} {sort.upper()}")


@pytest.mark.parametrize(
    "field, sort",
    [
        ("if(1=1,sleep(5),1)", "asc"),
        ("file_name, (select 1)", "asc"),
        ("file_name", "asc; drop table knowledge_file"),
        ("file_name", "asc, if(1=1,sleep(5),1)"),
        ("", "asc"),
        (None, "asc"),
        ("file_name", None),
        ("FILE_NAME", "asc"),
    ],
)
def test_anything_else_is_rejected(field, sort):
    with pytest.raises(ValueError):
        SpaceFileDao.order_field_text(field, sort)


def _endpoint_annotations(func_name: str) -> dict[str, str]:
    source = (_BACKEND_ROOT / "knowledge" / "api" / "endpoints" / "knowledge_space.py").read_text()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == func_name:
            return {a.arg: ast.unparse(a.annotation) for a in node.args.args + node.args.kwonlyargs if a.annotation}
    raise AssertionError(f"{func_name} not found")


@pytest.mark.parametrize("func_name", ["list_space_children", "search_space_children"])
def test_endpoints_type_order_params_with_the_whitelist(func_name):
    annotations = _endpoint_annotations(func_name)
    assert annotations["order_field"] == "SpaceFileOrderField"
    assert annotations["order_sort"] == "SpaceFileOrderSort"


def test_literal_aliases_match_dao_whitelist():
    from typing import get_args

    for field in get_args(SpaceFileOrderField):
        SpaceFileDao.order_field_text(field, "asc")
    for sort in get_args(SpaceFileOrderSort):
        SpaceFileDao.order_field_text("file_name", sort)
