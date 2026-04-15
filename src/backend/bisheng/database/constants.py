from enum import Enum

# Default Normal User Role'sID
DefaultRole = 2
# Super Admin RoleID
AdminRole = 1


# Some of the basiccategoryType
class MessageCategory(str, Enum):
    QUESTION = 'question'  # User Questions
    ANSWER = 'answer'  # Answers (legacy plain-text format)
    STREAM = 'stream'  # stream
    # v2.5 Agent-mode new categories
    AGENT_ANSWER = 'agent_answer'     # Agent final answer (JSON: msg/reasoning/tool_calls/steps)
    AGENT_THINKING = 'agent_thinking'  # Agent streaming reasoning chunk
    AGENT_TOOL_CALL = 'agent_tool_call'  # Agent tool invocation (start/end)
