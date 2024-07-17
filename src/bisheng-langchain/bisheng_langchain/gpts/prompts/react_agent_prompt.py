from typing import List, Union
from langchain_core.prompts.chat import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
    MessagesPlaceholder
)
from langchain_core.prompts.prompt import PromptTemplate
from langchain_core.messages import FunctionMessage, SystemMessage, ToolMessage, AIMessage, HumanMessage, ChatMessage


system_temp = """
{assistant_message}

Respond to the human as helpfully and accurately as possible. You have access to the following tools:

{tools}

Use a json blob to specify a tool by providing an action key (tool name) and an action_input key (tool input).

Valid "action" values: "Final Answer" or {tool_names}

Provide only ONE action per $JSON_BLOB, as shown:

```
{{
  "action": $TOOL_NAME,
  "action_input": $INPUT
}}
```

Follow this format:

Question: input question to answer
Thought: consider previous and subsequent steps
Action:
```
$JSON_BLOB
```
Observation: action result
... (repeat Thought/Action/Observation N times)
Thought: I know what to respond
Action:
```
{{
  "action": "Final Answer",
  "action_input": "Final response to human"
}}

Begin! Reminder to ALWAYS respond with a valid json blob of a single action. Use tools if necessary. Respond directly if appropriate. Format is Action:```$JSON_BLOB```then Observation
"""

human_temp = """Question: {input}

Thought: {agent_scratchpad}
(reminder to respond in a JSON blob no matter what)"""


react_agent_prompt = ChatPromptTemplate(
    input_variables=['agent_scratchpad', 'input', 'tool_names', 'tools', 'assistant_message'], 
    optional_variables=['chat_history'], 
    input_types={'chat_history': List[Union[AIMessage, HumanMessage, ChatMessage, SystemMessage, FunctionMessage, ToolMessage]]}, 
    messages=[
        SystemMessagePromptTemplate.from_template(system_temp),
        MessagesPlaceholder(variable_name='chat_history', optional=True), 
        HumanMessagePromptTemplate.from_template(human_temp)
    ]
)