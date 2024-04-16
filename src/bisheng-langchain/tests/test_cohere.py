def test_chat():
    from langchain_cohere import ChatCohere
    from langchain_core.messages import HumanMessage
    chat = ChatCohere()
    messages = [HumanMessage(content="knock knock")]
    print(chat(messages))


def test_llm():
    from langchain_cohere import Cohere

    llm = Cohere(model="command")
    print(llm.invoke("Come up with a pet name"))


def test_react_agent():
    from langchain_community.tools.tavily_search import TavilySearchResults
    from langchain_cohere import ChatCohere, create_cohere_react_agent
    from langchain.prompts import ChatPromptTemplate
    from langchain.agents import AgentExecutor

    llm = ChatCohere()

    internet_search = TavilySearchResults(max_results=4)
    internet_search.name = "internet_search"
    internet_search.description = "Route a user query to the internet"

    prompt = ChatPromptTemplate.from_template("{input}")

    agent = create_cohere_react_agent(
        llm,
        [internet_search],
        prompt
    )

    agent_executor = AgentExecutor(agent=agent, tools=[internet_search], verbose=True)

    agent_executor.invoke({
        "input": "In what year was the company that was founded as Sound of Music added to the S&P 500?",
    })


def test_retriever():
    from langchain_cohere import ChatCohere
    from langchain_cohere import CohereRagRetriever
    from langchain_core.documents import Document

    rag = CohereRagRetriever(llm=ChatCohere())
    print(rag.get_relevant_documents("What is cohere ai?"))


def test_embedding():
    from langchain_cohere import CohereEmbeddings

    embeddings = CohereEmbeddings(model="embed-english-light-v3.0")
    print(embeddings.embed_documents(["This is a test document."]))


# test_chat()
# test_llm()
test_react_agent()
# test_retriever()
# test_embedding()