from langchain.pydantic_v1 import BaseModel, Field
from langchain.tools import tool


class CalculatorInput(BaseModel):
    expression: str = Field(
        description="The input to this tool should be a mathematical expression, a couple examples are `200*7` or `5000/2*10`p"
    )


@tool("calculator")
def calculater(expression):
    """Useful to perform any mathematical calculations,
    like sum, minus, multiplication, division, etc.

    """
    try:
        return eval(expression)
    except SyntaxError:
        return "Error: Invalid syntax in mathematical expression"
