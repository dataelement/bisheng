"""A bounded real-number arithmetic interpreter, not a Python sandbox."""

import ast
import math
import operator

from langchain_classic.tools import tool
from pydantic import BaseModel, Field

_MAX_EXPRESSION_LENGTH = 4096
_MAX_NODES = 256
_MAX_DEPTH = 32
_MAX_EXPONENT = 1000
_MAX_INTEGER_BITS = 1024
_MAX_MAGNITUDE = 1e308
_MAX_FACTORIAL = 170
_MAX_ARGUMENTS = 16

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
# Each entry is a fixed callable and its minimum/maximum positional arity.
# No user-selected attributes, arbitrary callables, symbolic parsing or iteration.
_FUNCTIONS = {
    "abs": (abs, 1, 1),
    "round": (round, 1, 2),
    "min": (min, 2, _MAX_ARGUMENTS),
    "max": (max, 2, _MAX_ARGUMENTS),
    "sqrt": (math.sqrt, 1, 1),
    "exp": (math.exp, 1, 1),
    "log": (math.log, 1, 2),
    "ln": (math.log, 1, 1),
    "log10": (math.log10, 1, 1),
    "log2": (math.log2, 1, 1),
    "sin": (math.sin, 1, 1),
    "cos": (math.cos, 1, 1),
    "tan": (math.tan, 1, 1),
    "asin": (math.asin, 1, 1),
    "acos": (math.acos, 1, 1),
    "atan": (math.atan, 1, 1),
    "atan2": (math.atan2, 2, 2),
    "sinh": (math.sinh, 1, 1),
    "cosh": (math.cosh, 1, 1),
    "tanh": (math.tanh, 1, 1),
    "floor": (math.floor, 1, 1),
    "ceil": (math.ceil, 1, 1),
    "trunc": (math.trunc, 1, 1),
    "fabs": (math.fabs, 1, 1),
    "degrees": (math.degrees, 1, 1),
    "radians": (math.radians, 1, 1),
    "factorial": (math.factorial, 1, 1),
}
_CONSTANTS = {"pi": math.pi, "e": math.e, "E": math.e, "tau": math.tau}


def _checked_number(value: int | float) -> int | float:
    # Exact types exclude bool and objects with overloaded arithmetic methods.
    if type(value) is int:  # noqa: E721  # exact type, bool must not pass as int
        if value.bit_length() > _MAX_INTEGER_BITS:
            raise ValueError("Integer result exceeds calculator limit")
    elif type(value) is not float:  # noqa: E721  # exact type, bool must not pass as int
        raise ValueError("Only real numbers are supported")
    if not math.isfinite(value) or abs(value) > _MAX_MAGNITUDE:
        raise ValueError("Number exceeds calculator limit")
    return value


def _power(base: int | float, exponent: int | float) -> int | float:
    if abs(exponent) > _MAX_EXPONENT:
        raise ValueError("Exponent exceeds calculator limit")
    if base < 0 and exponent != int(exponent):
        raise ValueError("Only real results are supported")
    # Reject growth before computing the power, including nested exponentiation.
    if base and abs(base) != 1:
        growth = exponent * math.log2(abs(base))
        if growth > min(_MAX_INTEGER_BITS - 1, math.log2(_MAX_MAGNITUDE)):
            raise ValueError("Power result exceeds calculator limit")
    return _checked_number(base**exponent)


def _interpret(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant):
        return _checked_number(node.value)
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd | ast.USub):
        value = _interpret(node.operand)
        return _checked_number(value if isinstance(node.op, ast.UAdd) else -value)
    if isinstance(node, ast.BinOp):
        left, right = _interpret(node.left), _interpret(node.right)
        if isinstance(node.op, ast.Pow):
            return _power(left, right)
        operation = _BINARY_OPERATORS.get(type(node.op))
        if operation is not None:
            return _checked_number(operation(left, right))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        name = node.func.id
        if name == "pow" and len(node.args) == 2:
            return _power(*[_interpret(arg) for arg in node.args])
        function_spec = _FUNCTIONS.get(name)
        if function_spec is not None:
            function, minimum, maximum = function_spec
            if minimum <= len(node.args) <= maximum:
                args = [_interpret(arg) for arg in node.args]
                if name == "factorial" and (type(args[0]) is not int or not 0 <= args[0] <= _MAX_FACTORIAL):  # noqa: E721  # exact type, bool must not pass as int
                    raise ValueError("Factorial argument exceeds calculator limit")
                if name == "round" and len(args) == 2:
                    if type(args[1]) is not int or abs(args[1]) > _MAX_EXPONENT:  # noqa: E721  # exact type, bool must not pass as int
                        raise ValueError("Rounding precision exceeds calculator limit")
                return _checked_number(function(*args))
    raise ValueError("Unsupported mathematical expression")


def _calculate(expression: str) -> int | float:
    if not isinstance(expression, str) or len(expression) > _MAX_EXPRESSION_LENGTH:
        raise ValueError("Expression exceeds calculator length limit")
    tree = ast.parse(expression.strip(), mode="eval")
    # Check complexity iteratively before the recursive arithmetic interpreter.
    pending = [(tree, 0)]
    count = 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > _MAX_NODES or depth > _MAX_DEPTH:
            raise ValueError("Expression exceeds calculator complexity limit")
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    return _interpret(tree.body)


class CalculatorInput(BaseModel):
    expression: str = Field(
        description=(
            "A real-number mathematical expression (maximum 4096 characters). "
            "Operators: +, -, *, /, //, %, **; parentheses and unary +/- are supported. "
            "Constants: pi, e, E, tau. Functions: " + ", ".join([*_FUNCTIONS, "pow"]) + ". "
            "Use positional numeric arguments only. Exponents are limited to +/-1000, "
            "factorial to 170, and finite values to magnitude 1e308."
        ),
        examples=["200*7"],
    )


@tool("calculator", args_schema=CalculatorInput)
def calculator(expression: str) -> int | float | str:
    """Perform bounded real-number arithmetic using the documented operators and functions."""
    try:
        return _calculate(expression)
    except SyntaxError:
        return "Error: Invalid syntax in mathematical expression"
    except (ValueError, TypeError, ArithmeticError, RecursionError):
        # Invalid user mathematics is an expected tool result, never executable code.
        return "Error: Invalid or unsupported mathematical expression, or calculator limit exceeded"
