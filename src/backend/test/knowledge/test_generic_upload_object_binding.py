"""Each generic upload writer must bind its exact staged object for refresh."""

import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "path,function",
    [
        ("bisheng/api/v1/endpoints.py", "create_upload_file"),
        ("bisheng/knowledge/api/endpoints/knowledge.py", "upload_file"),
        ("bisheng/knowledge/api/endpoints/knowledge.py", "upload_knowledge_file"),
    ],
)
def test_upload_binds_exact_server_object_before_preview_reference(path, function):
    tree = ast.parse((Path(__file__).resolve().parents[2] / path).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == function)
    calls = [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    binding = [n for n in calls if n.func.attr == "bind_owned_object"]
    assert len(binding) == 1
    keywords = {k.arg: ast.unparse(k.value) for k in binding[0].keywords}
    assert keywords["object_name"] == "object_name"
    assert keywords["login_user"] == "login_user"
    assert keywords["bucket"] == "minio.tmp_bucket"
    issue = next(n for n in calls if n.func.attr == "issue")
    assert binding[0].lineno < issue.lineno
