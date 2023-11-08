from credit_report import Reprot
from langchain.agents import initialize_agent
from langchain.agents import AgentType
from langchain.chains import LLMChain
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate
from langchain.tools import  Tool
from langchain.utilities.google_search import GoogleSearchAPIWrapper
from langchain.memory import ConversationBufferMemory

async def async_test(chains, agents):
    report =  Reprot(chains=chains, agents=agents, input_key="report_name", verbose=True)
    result = await report.arun("贷后报告")
    print(result)
    
    
def test(chains, agents):
    report =  Reprot(chains=chains, agents=agents, input_key="report_name", verbose=True)
    result = report("贷后报告")
    print(result)


if __name__ == "__main__":
    search = GoogleSearchAPIWrapper()
    tools = [
        Tool(
            name = "Current Search",
            func=search.run,
            description="useful for when you need to answer questions about current events or the current state of the world"
        ),
    ]
    llm = OpenAI()
    memory = ConversationBufferMemory(memory_key="chat_history")
    agent1 = initialize_agent(tools, llm, agent=AgentType.CONVERSATIONAL_REACT_DESCRIPTION, verbose=True, memory=memory)
    input="查询中国人口数量"
    
    agents = [
            {
                "object": agent1,
                "input": input,
                "node_id": "agent_1" 
            }
        ]

    prompt = PromptTemplate.from_template("回答下面问题: {question}")
    llm_chain = LLMChain(llm=llm, prompt=prompt)
    
    prompt2 = PromptTemplate.from_template("下列国家的首都是: {country}")
    llm_chain2 = LLMChain(llm=llm, prompt=prompt2)
    
    input1 = {"question": "世界上有多少个国家和地区"}
    input2 = {"country": "中国"}
    
    chains = [
        {
            "object": llm_chain,
            "input": input1,
            "node_id": "chain_1"
        },
        {
            "object":  llm_chain2,
            "input": input2,
            "node_id": "chain_2"
        }
    ]
    
    import asyncio
    asyncio.run(async_test(chains=chains, agents=agents))
    test(chains=chains, agents=agents)