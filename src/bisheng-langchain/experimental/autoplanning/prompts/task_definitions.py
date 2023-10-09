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


TASK2COMPONENTS = {
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


COMPONENT_PARAMS = {
    'InputFileNode': {'require': {},
                      'option': {}
                     },
    'PyPDFLoader': {'require': {},
                    'option': {'metadata': {}}
                   },
    'RecursiveCharacterTextSplitter': {'require': {},
                                       'option': {'chunk_overlap': 200, 'chunk_size': 1000, 'separator_type': 'Text', 'separators': '\n'}
                                      },
    'OpenAIEmbeddings': {'require': {'openai_api_key': str, 'openai_proxy': str},
                         'option': {'model': 'text-embedding-ada-002'}
                        },
    'Milvus': {'require': {'collection_name': str},
               'option': {'connection_args': {"host":"192.168.106.12", "port":"19530", "user":"", "password":"", "secure":False},
                          'search_kwargs': {}
                         }
              },
    'ChatOpenAI': {'require': {'openai_api_key': str, 'openai_proxy': str},
                   'option': {'model_name': 'gpt-3.5-turbo-0613', 'temperature': 0.7}
                  },
    'CombineDocsChain': {'require': {},
                         'option': {'token_max': -1, 'chain_type': 'stuff'}
                        },
    'RetrievalQA': {'require': {},
                    'option': {'input_key': 'query', 'output_key': 'result', 'return_source_documents': False}
                   },
    'Search': {'require': {'serpapi_api_key': str},
               'option': {}
              },
}


def jsonFixer(data):
    data = json.dumps(data, indent=4)
    return data.replace("{", "{{").replace("}", "}}")


TASK_NAMES = [task["name"] for task in TASKS]

TASK_DESCRIPTIONS = jsonFixer(TASKS)