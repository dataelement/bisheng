from qianfan.common.tool.base_tool import BaseTool


class CallUserTool(BaseTool):
    """
    A tool to call the user for input.
    """

    name = "call_user_tool"
    description = "A tool to call the user for input."

    def __init__(self, user_input: str):
        self.user_input = user_input

    def run(self) -> str:
        """
        Run the tool and return the user input.
        """
        return self.user_input
