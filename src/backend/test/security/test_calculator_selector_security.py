"""Regression coverage for calculator and model-output code injection."""

import ast
import importlib
import math
from pathlib import Path
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from bisheng_langchain.gpts.auto_tool_selected import ToolInfo, ToolSelector
from bisheng_langchain.gpts.tools.calculator.tool import calculator


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("200*7", 1400),
        ("2+3*4-5/2", 11.5),
        ("(2+3)*4", 20),
        ("-2**2", -4),
        ("2**-3", 0.125),
        ("17//3 + 17%3", 7),
        ("1e3 + .5", 1000.5),
        ("sqrt(81) + abs(-2)", 11),
        ("sin(pi/2) + cos(0) + log(e)", 3),
        ("log(8, 2) + log10(100)", 5),
        ("floor(1.9) + ceil(1.1)", 3),
        ("round(2.125, 2)", 2.12),
        ("pow(2, 10)", 1024),
        ("factorial(5)", 120),
        (" 2 + 3 ", 5),
        ("min(1, 2) + max(1, 2)", 3),
        ("ln(E) + log2(8)", 4),
        ("degrees(pi) + radians(180)", 180 + math.pi),
        ("atan2(0, 1) + asin(0) + acos(1) + atan(0)", 0),
        ("sinh(0) + cosh(0) + tanh(0) + tan(0)", 1),
        ("trunc(-1.5) + fabs(-2)", 1),
    ],
)
def test_calculator_ordinary_math(expression, expected):
    assert float(calculator.invoke({"expression": expression})) == pytest.approx(expected)


def test_calculator_rejects_report_command_payloads(monkeypatch):
    import os

    system = Mock(return_value=0)
    popen = Mock(return_value=Mock(read=Mock(return_value="command output")))
    monkeypatch.setattr(os, "system", system)
    monkeypatch.setattr(os, "popen", popen)
    for expression in [
        "__import__('os').system('id')",
        "__import__('os').popen('id; uname -sm').read()",
    ]:
        result = calculator.invoke({"expression": expression})
        assert isinstance(result, str) and result.startswith("Error:")
    system.assert_not_called()
    popen.assert_not_called()


def test_calculator_rejects_report_file_payload(tmp_path):
    marker = tmp_path / "pwned.txt"
    expression = f"open({str(marker)!r},'w').write('RCE via calculator eval')"
    result = calculator.invoke({"expression": expression})
    assert not marker.exists()
    assert isinstance(result, str) and result.startswith("Error:")


@pytest.mark.parametrize(
    "expression",
    [
        "().__class__.__bases__[0].__subclasses__()",
        "math.sqrt(4)",
        "sympy.sympify('2+2')",
        "[1, 2]",
        "{'a': 1}",
        "'x'*3",
        "True+1",
        "1j",
        "lambda: 1",
        "(x for x in [1])",
        "[x for x in [1]]",
        "sqrt(*[4])",
        "round(1, ndigits=2)",
        "1 if True else 2",
        "1 < 2",
        "1 << 2",
        "unknown(1)",
        "unknown",
    ],
)
def test_calculator_rejects_non_arithmetic(expression):
    result = calculator.invoke({"expression": expression})
    assert isinstance(result, str) and result.startswith("Error:")


@pytest.mark.parametrize("expression", ["1/0", "sqrt(-1)", "1e309", "exp(1000)", "(-1)**0.5", "2+"])
def test_calculator_errors_are_safe_and_predictable(expression):
    result = calculator.invoke({"expression": expression})
    assert isinstance(result, str) and result.startswith("Error:")


def test_calculator_size_limit_precedes_parsing(monkeypatch):
    parser = Mock(side_effect=AssertionError("oversized input reached parser"))
    with monkeypatch.context() as patch:
        patch.setattr(ast, "parse", parser)
        result = calculator.invoke({"expression": "1" + " " * 4096})
    assert isinstance(result, str) and result.startswith("Error:")
    parser.assert_not_called()


def test_calculator_rejects_depth_and_node_limits():
    for expression in ["-" * 40 + "1", "+".join(["1"] * 150), "sqrt(" * 40 + "1" + ")" * 40]:
        result = calculator.invoke({"expression": expression})
        assert isinstance(result, str) and result.startswith("Error:")


def test_calculator_limits_expensive_operations_before_execution():
    module = importlib.import_module("bisheng_langchain.gpts.tools.calculator.tool")
    # These inputs are deliberately not run by the vulnerable baseline.
    if not hasattr(module, "_MAX_EXPONENT"):
        pytest.fail("calculator has no pre-operation resource bounds")
    for expression in [
        "2**100000000",
        "pow(2, 100000000)",
        "9**9**9",
        "factorial(100000000)",
        "10**1000",
        "(10**200)*(10**200)",
        "2**-1001",
    ]:
        assert calculator.invoke({"expression": expression}).startswith("Error:")
    assert calculator.invoke({"expression": "2**1000"}) == 2**1000
    assert math.isfinite(calculator.invoke({"expression": "exp(10)"}))


def test_calculator_resource_boundaries():
    # Full binary trees distinguish the node budget from the depth budget.
    expression = "1"
    for _ in range(6):
        expression = f"({expression}+{expression})"
    assert calculator.invoke({"expression": expression}) == 64
    assert calculator.invoke({"expression": f"({expression}+{expression})"}).startswith("Error:")
    assert calculator.invoke({"expression": "1" + " " * 4095}) == 1
    assert calculator.invoke({"expression": "-" * 30 + "1"}) == 1
    for expression in ["factorial(171)", "round(1.5, 1001)", "round(1.5, 1.2)", "pow(2, 3, 5)"]:
        assert calculator.invoke({"expression": expression}).startswith("Error:")


def test_calculator_factory_registration_uses_safe_tool():
    from bisheng_langchain.gpts.load_tools import load_tools

    loaded = load_tools({"calculator": {}})[0]
    assert loaded is calculator
    assert loaded.name == "calculator"
    assert loaded.invoke({"expression": "200*7"}) == 1400
    assert loaded.invoke({"expression": "__import__('os').system('id')"}).startswith("Error:")


async def test_calculator_async_invocation_preserves_safe_behavior():
    assert await calculator.ainvoke({"expression": "sqrt(16)"}) == 4
    result = await calculator.ainvoke({"expression": "__import__('os').system('id')"})
    assert result.startswith("Error:")


def select(content):
    llm = RunnableLambda(lambda _: AIMessage(content=content))
    return ToolSelector(
        llm=llm,
        tools=[ToolInfo(tool_name=name, tool_description=name) for name in ["calculator", "arxiv"]],
    ).select("task", "description")


@pytest.mark.parametrize("content", ['["calculator", "arxiv"]', "['calculator', 'arxiv']"])
def test_selector_preserves_json_and_documented_python_list(content):
    assert set(select(content)) == {"calculator", "arxiv"}
    assert select("['calculator', 'unknown', 'calculator']") == ["calculator"]
    assert select("[]") == []


def test_selector_rejects_report_file_payload(tmp_path):
    marker = tmp_path / "selector.txt"
    content = f"[open({str(marker)!r},'w').write('RCE via ToolSelector eval of model output')]"
    assert select(content) == []
    assert not marker.exists()


@pytest.mark.parametrize(
    "content",
    [
        "('calculator',)",
        "{'calculator'}",
        "{'calculator': 1}",
        "'calculator'",
        "[1, 'calculator']",
        "[True, 'calculator']",
        "[['calculator']]",
        "null",
        "['calculator'] + ['arxiv']",
        "[x for x in ['calculator']]",
        "not a list",
        '```json\n["calculator"]\n```',
        "[" * 100 + "]" * 100,
    ],
)
def test_selector_rejects_wrong_types_and_expressions(content):
    assert select(content) == []


def test_selector_bounds_output_before_parsing(monkeypatch):
    parser = Mock(side_effect=AssertionError("oversized input reached parser"))
    monkeypatch.setattr(ast, "literal_eval", parser)
    assert select("['calculator']" + " " * 16384) == []
    parser.assert_not_called()


def test_selector_bounded_list_and_name_sizes():
    import json

    assert select(json.dumps(["calculator"] * 256)) == ["calculator"]
    assert select(json.dumps(["calculator"] * 257)) == []
    assert select(repr(["calculator"] * 257)) == []
    assert select(json.dumps(["calculator", "x" * 257])) == []
    assert select([{"type": "text", "text": "['calculator']"}]) == []


def test_selector_preserves_order_and_propagates_model_failure():
    assert select('["arxiv", "calculator", "arxiv"]') == ["arxiv", "calculator"]

    def fail(_):
        raise RuntimeError("model unavailable")

    with pytest.raises(RuntimeError, match="model unavailable"):
        ToolSelector(llm=RunnableLambda(fail), tools=[]).select("task", "description")


def test_no_dynamic_execution_or_sympy_parser_in_fixed_modules():
    root = Path(__file__).resolve().parents[2]
    for relative in ["bisheng_langchain/gpts/tools/calculator/tool.py", "bisheng_langchain/gpts/auto_tool_selected.py"]:
        tree = ast.parse((root / relative).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec", "compile", "sympify", "parse_expr"}
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                assert not any(name.startswith("sympy") for name in names)
