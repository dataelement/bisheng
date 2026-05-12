"""Signature-only tests for file_type query parameter threading.

Strategy: avoid importing KnowledgeSpaceService / the FastAPI app, which pull
in a long chain of repo modules. Use AST and `inspect` to verify that
file_type is wired through the service signature and the endpoint signature.

The actual filter behavior is covered by test_space_file_dao_filter.py.
"""
import ast
import inspect
from pathlib import Path

import pytest


_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "bisheng"


def _find_function_def(source: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def test_service_list_space_children_accepts_file_type():
    """`KnowledgeSpaceService.list_space_children` signature must include `file_type`."""
    svc_file = _BACKEND_ROOT / "knowledge" / "domain" / "services" / "knowledge_space_service.py"
    fn = _find_function_def(svc_file.read_text(), "list_space_children")
    assert fn is not None, "list_space_children not found in service"
    arg_names = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    assert "file_type" in arg_names, f"file_type missing from service signature: {arg_names}"


def test_dao_async_list_children_accepts_file_type():
    """`SpaceFileDao.async_list_children` signature must include `file_type`."""
    dao_file = _BACKEND_ROOT / "knowledge" / "domain" / "models" / "knowledge_space_file.py"
    fn = _find_function_def(dao_file.read_text(), "async_list_children")
    assert fn is not None, "async_list_children not found"
    arg_names = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    assert "file_type" in arg_names, f"file_type missing from DAO signature: {arg_names}"


def test_endpoint_route_accepts_file_type_query():
    """The /children endpoint handler must accept a `file_type` query param."""
    ep_file = _BACKEND_ROOT / "knowledge" / "api" / "endpoints" / "knowledge_space.py"
    source = ep_file.read_text()
    # Endpoint handler function exists with file_type in its signature
    # Match any function whose body or decorators mention the /children route
    tree = ast.parse(source)
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arg_names = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
        if "file_type" not in arg_names:
            continue
        # Check decorators for the /children path
        for dec in node.decorator_list:
            try:
                dec_src = ast.unparse(dec)
            except AttributeError:
                continue
            if "/children" in dec_src or "children" in dec_src.lower():
                found = True
                break
        if found:
            break
    assert found, "no endpoint handler with /children decorator + file_type kwarg found"
