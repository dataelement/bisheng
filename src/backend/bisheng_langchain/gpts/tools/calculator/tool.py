import math
from math import *

import sympy
from pydantic import BaseModel, Field
from langchain.tools import tool
from sympy import *


class CalculatorInput(BaseModel):
    expression: str = Field(
        description="The input to this tool should be a mathematical expression using only Python's built-in mathematical operators.",
        examples=['200*7'],
    )


@tool("calculator", args_schema=CalculatorInput)
def calculator(expression):
    """Useful to perform any mathematical calculations,
    like sum, minus, multiplication, division, etc
    """
    try:
        return eval(expression)
    except SyntaxError:
        return "Error: Invalid syntax in mathematical expression"
