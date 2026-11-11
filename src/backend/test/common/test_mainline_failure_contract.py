"""Release-line context/credit contracts remain intact under failure provenance.

Load actual provider bodies and context conversion without initializing application
services. Only the external provider and application import plumbing are replaced.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import openai
import pytest
from langchain_core.exceptions import ContextOverflowError

from bisheng.common.services.failure_context import FailureContextAdapter, failure_boundary
from bisheng.common.services.llm_error_classifier import Behavior, classify_behavior, classify_for_event

ROOT = Path(__file__).resolve().parents[2] / "bisheng"


def _context_converter(monkeypatch):
    ns = {"__name__": "_failure_contract_context"}
    module = ModuleType(ns["__name__"])
    monkeypatch.setitem(sys.modules, ns["__name__"], module)
    exec(compile((ROOT / "llm/domain/llm/exceptions.py").read_text(), "exceptions.py", "exec"), ns)
    tree = ast.parse((ROOT / "llm/domain/llm/context_overflow.py").read_text())
    tree.body = [
        node
        for node in tree.body
        if not (isinstance(node, ast.ImportFrom) and node.module == "bisheng.llm.domain.llm.exceptions")
    ]
    module.__dict__.update(ns)
    exec(compile(tree, "context_overflow.py", "exec"), module.__dict__)
    return module.as_context_overflow


@pytest.mark.parametrize("method", ["_generate", "_agenerate"])
async def test_provider_boundary_keeps_context_overflow_retry_contract(method, monkeypatch):
    convert = _context_converter(monkeypatch)
    tree = ast.parse((ROOT / "llm/domain/llm/llm.py").read_text())
    helper = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_raise_as_context_overflow"
    )
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BishengLLM")
    function = next(
        node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method
    )
    function.decorator_list = [
        node
        for node in function.decorator_list
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "failure_boundary"
    ]
    request = httpx.Request("POST", "https://model.invalid/v1/chat/completions")
    original = openai.BadRequestError(
        "This model's maximum context length is 32768 tokens. However, you requested 0 output tokens and your prompt contains at least 32769 input tokens",
        response=httpx.Response(400, request=request),
        body={"error": {"code": "context_length_exceeded"}},
    )

    def sync(*args, **kwargs):
        raise original

    async def asynchronous(*args, **kwargs):
        raise original

    ns = {"as_context_overflow": convert, "failure_boundary": failure_boundary}
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[future, helper, function], type_ignores=[])), "llm.py", "exec"
        ),
        ns,
    )
    owner = SimpleNamespace(
        llm=SimpleNamespace(_generate=sync, _agenerate=asynchronous), model_info=SimpleNamespace(name="Test model")
    )
    with pytest.raises(ContextOverflowError) as caught:
        if method == "_generate":
            ns[method](owner, [])
        else:
            await ns[method](owner, [])
    error = caught.value
    assert isinstance(error, openai.BadRequestError)
    assert classify_behavior(error) is Behavior.FAIL_FAST
    classified = classify_for_event(error)
    assert classified.error_type == "context_overflow"
    assert classified.error_code == 11075
    assert FailureContextAdapter.from_error(error)["category"] == "model_service"
