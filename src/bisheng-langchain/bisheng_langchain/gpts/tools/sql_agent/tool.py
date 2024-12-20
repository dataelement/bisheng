from typing import Type, Optional, TypedDict, Annotated, Any, Literal

from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import AnyMessage, AIMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableWithFallbacks
from langchain_core.tools import BaseTool, tool
from langgraph.constants import END, START
from langgraph.graph import add_messages, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def handle_tool_error(state) -> dict:
    error = state.get("error")
    tool_calls = state["messages"][-1].tool_calls
    return {
        "messages": [
            ToolMessage(
                content=f"Error: {repr(error)}\n please fix your mistakes.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
    }


def create_tool_node_with_fallback(tools: list) -> RunnableWithFallbacks[Any, dict]:
    """
    Create a ToolNode with a fallback to handle errors and surface them to the agent.
    """
    return ToolNode(tools).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )


class SubmitFinalAnswer(BaseModel):
    """Submit the final answer to the user based on the query results."""

    final_answer: str = Field(..., description="The final answer to the user")

class QueryDBTool(BaseTool):
    name = "db_query_tool"
    description = """Execute a SQL query against the database and get back the result.
        If the query is not correct, an error message will be returned.
        If an error is returned, rewrite the query, check the query, and try again."""

    db: SQLDatabase

    def _run(self, query: str, run_manager: Optional[CallbackManagerForToolRun] = None):
        result = self.db.run_no_throw(query)
        if not result:
            return "Error: Query failed. Please rewrite your query and try again."
        return result

class SqlAgentAPIWrapper(BaseModel):
    llm: BaseLanguageModel = Field(description="llm to use for sql agent")
    sql_address: str = Field(description="sql database address for SQLDatabase uri")

    db: Optional[SQLDatabase]
    list_tables_tool: Optional[BaseTool]
    get_schema_tool: Optional[BaseTool]
    db_query_tool: Optional[BaseTool]
    query_check: Optional[Any]
    query_gen: Optional[Any]
    workflow: Optional[StateGraph]
    app: Optional[Any]

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.llm = kwargs.get('llm')
        self.sql_address = kwargs.get('sql_address')

        self.db = SQLDatabase.from_uri(self.sql_address)
        toolkit = SQLDatabaseToolkit(db=self.db, llm=self.llm)
        tools = toolkit.get_tools()
        self.list_tables_tool = next(tool for tool in tools if tool.name == "sql_db_list_tables")
        self.get_schema_tool = next(tool for tool in tools if tool.name == "sql_db_schema")
        self.db_query_tool = QueryDBTool(db=self.db)

        self.query_check = self.init_query_check()
        self.query_gen = self.init_query_gen()

        # Define a new graph
        self.workflow = StateGraph(State)
        self.init_workflow()
        self.app = self.workflow.compile(checkpointer=False)

    def init_workflow(self):
        self.workflow.add_node("first_tool_call", self.first_tool_call)
        self.workflow.add_node(
            "list_tables_tool", create_tool_node_with_fallback([self.list_tables_tool])
        )

        self.workflow.add_node("get_schema_tool", create_tool_node_with_fallback([self.get_schema_tool]))

        model_get_schema = self.llm.bind_tools(
            [self.get_schema_tool]
        )
        self.workflow.add_node(
            "model_get_schema",
            lambda state: {
                "messages": [model_get_schema.invoke(state["messages"])],
            },
        )

        self.workflow.add_node("query_gen", self.query_gen_node)
        self.workflow.add_node("correct_query", self.model_check_query)

        self.workflow.add_node("execute_query", create_tool_node_with_fallback([self.db_query_tool]))

        self.workflow.add_edge(START, "first_tool_call")
        self.workflow.add_edge("first_tool_call", "list_tables_tool")
        self.workflow.add_edge("list_tables_tool", "model_get_schema")
        self.workflow.add_edge("model_get_schema", "get_schema_tool")
        self.workflow.add_edge("get_schema_tool", "query_gen")
        self.workflow.add_conditional_edges(
            "query_gen",
            self.should_continue,
        )
        self.workflow.add_edge("correct_query", "execute_query")
        self.workflow.add_edge("execute_query", "query_gen")

    @staticmethod
    def should_continue(state: State) -> Literal[END, "correct_query", "query_gen"]:
        messages = state["messages"]
        last_message = messages[-1]
        # If there is a tool call, then we finish
        if getattr(last_message, "tool_calls", None):
            return END
        if last_message.content.startswith("Error:"):
            return "query_gen"
        else:
            return "correct_query"

    def init_query_check(self):
        query_check_system = """You are a SQL expert with a strong attention to detail.
        Double check the SQLite query for common mistakes, including:
        - Using NOT IN with NULL values
        - Using UNION when UNION ALL should have been used
        - Using BETWEEN for exclusive ranges
        - Data type mismatch in predicates
        - Properly quoting identifiers
        - Using the correct number of arguments for functions
        - Casting to the correct data type
        - Using the proper columns for joins

        If there are any of the above mistakes, rewrite the query. If there are no mistakes, just reproduce the original query.

        You will call the appropriate tool to execute the query after running this check."""

        query_check_prompt = ChatPromptTemplate.from_messages(
            [("system", query_check_system), ("placeholder", "{messages}")]
        )
        query_check = query_check_prompt | self.llm.bind_tools(
            [self.db_query_tool], tool_choice="required"
        )
        return query_check

    def first_tool_call(self, state: State) -> dict[str, list[AIMessage]]:
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "sql_db_list_tables",
                            "args": {},
                            "id": "tool_abcd123",
                        }
                    ],
                )
            ]
        }

    def model_check_query(self, state: State) -> dict[str, list[AIMessage]]:
        """
        Use this tool to double-check if your query is correct before executing it.
        """
        return {"messages": [self.query_check.invoke({"messages": [state["messages"][-1]]})]}

    def init_query_gen(self):
        # Add a node for a model to generate a query based on the question and schema
        query_gen_system = """You are a SQL expert with a strong attention to detail.Given an input question, output a syntactically correct SQL query to run, then look at the results of the query and return the answer.DO NOT call any tool besides SubmitFinalAnswer to submit the final answer.When generating the query:Output the SQL query that answers the input question without a tool call.Unless the user specifies a specific number of examples they wish to obtain, always limit your query to at most 10 results.You can order the results by a relevant column to return the most interesting examples in the database.Never query for all the columns from a specific table, only ask for the relevant columns given the question.If you get an error while executing a query, rewrite the query and try again.If you get an empty result set, you should try to rewrite the query to get a non-empty result set. NEVER make stuff up if you don't have enough information to answer the query... just say you don't have enough information.If you have enough information to answer the input question, simply invoke the appropriate tool to submit the final answer to the user.DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.) to the database."""
        query_gen_prompt = ChatPromptTemplate.from_messages(
            [("system", query_gen_system), ("placeholder", "{messages}")]
        )
        query_gen = query_gen_prompt | self.llm.bind_tools(
            [SubmitFinalAnswer]
        )
        return query_gen

    def query_gen_node(self, state: State) -> Any:
        message = self.query_gen.invoke(state)

        # Sometimes, the LLM will hallucinate and call the wrong tool. We need to catch this and return an error message.
        tool_messages = []
        if message.tool_calls:
            for tc in message.tool_calls:
                if tc["name"] != "SubmitFinalAnswer":
                    tool_messages.append(
                        ToolMessage(
                            content=f"Error: The wrong tool was called: {tc['name']}. Please fix your mistakes. Remember to only call SubmitFinalAnswer to submit the final answer. Generated queries should be outputted WITHOUT a tool call.",
                            tool_call_id=tc["id"],
                        )
                    )
        else:
            tool_messages = []
        return {"messages": [message] + tool_messages}

    def run(self, query: str) -> str:
        messages = self.app.invoke({"messages": [("user", query)]}, config={
            'recursion_limit': 50
        })
        return messages["messages"][-1].tool_calls[0]["args"]["final_answer"]

    def arun(self, query: str) -> str:
        return self.run(query)


class SqlAgentInput(BaseModel):
    query: str = Field(description="用户数据查询需求（需要尽可能完整、准确）")


class SqlAgentTool(BaseTool):
    name = "sql_agent"
    description = "回答与 SQL 数据库有关的问题。给定用户问题，将从数据库中获取可用的表以及对应 DDL，生成 SQL 查询语句并进行执行，最终得到执行结果。"
    args_schema: Type[BaseModel] = SqlAgentInput
    api_wrapper: SqlAgentAPIWrapper

    def _run(
            self,
            query: str,
            run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Use the tool."""
        return self.api_wrapper.run(query)


if __name__ == '__main__':
    from langchain_openai import AzureChatOpenAI

    llm = AzureChatOpenAI()
    sql_agent_tool = SqlAgentTool(
        api_wrapper=SqlAgentAPIWrapper(
            llm=llm,
            sql_address="sqlite:///Chinook.db",
        )
    )

    result = sql_agent_tool.run("Which sales agent made the most in sales in 2009?")
    print(result)
