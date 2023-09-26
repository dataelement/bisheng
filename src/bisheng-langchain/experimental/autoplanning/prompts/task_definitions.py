import json


TASKS = [
    {
        "name": "FileRetrievalQA",
        "description": "Question and answer based on the content of the upload file.",
        "master_node": "RetrievalQA"
    },
    {
        "name": "KnowledgeRetrievalQA",
        "description": "Question and answer on the selected knowledge base.",
        "master_node": "RetrievalQA"
    },
    {
        "name": "ConversationWithLLm",
        "description": "Conversation with large language model",
        "master_node": "ConversationChain"
    },
    {
        "name": "SQLAnalysis",
        "description": "Database query and analysis through natural language",
        "master_node": "SQLAgent"
    },
    {
        "name": "CSVAnalysis",
        "description": "CSV file query and analysis through natural language",
        "master_node": "CSVAgent"
    },
    {
        "name": "Calculator",
        "description": "Useful for when you need to answer questions about math.",
        "master_node": "Calculator"
    },
    {
        "name": "SerpAPI",
        "description": "Useful for when you need to answer questions about current events or look up external information",
        "master_node": "Search"
    },
]


COMPONENTS = {
    'FileRetrievalQA': ['InputFileNode', 'PyPDFLoader', 'RecursiveCharacterTextSplitter',
                        'OpenAIEmbeddings', 'Milvus', 'ChatOpenAI', 'CombineDocsChain',
                        'RetrievalQA'],
    'KnowledgeRetrievalQA': ['OpenAIEmbeddings', 'Milvus', 'ChatOpenAI',
                             'CombineDocsChain', 'RetrievalQA'],
    'ConversationWithLLm': ['ChatOpenAI', 'ConversationChain'],
    'SQLAnalysis': ['ChatOpenAI', 'SQLAgent'],
    'CSVAnalysis': ['ChatOpenAI', 'CSVAgent'],
    'Calculator': ['ChatOpenAI', 'Calculator'],
    'SerpAPI': ['Search'],
}


def jsonFixer(data):
    data = json.dumps(data, indent=4)
    return data.replace("{", "{{").replace("}", "}}")


TASK_NAMES = [task["name"] for task in TASKS]

TASK_DESCRIPTIONS = jsonFixer(TASKS)