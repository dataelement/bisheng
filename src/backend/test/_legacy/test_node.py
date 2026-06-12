import requests

ALL_NODE = {
    'chains': {
        'TransformChain', 'ConversationalRetrievalChain', 'LoaderOutputChain', 'MultiRuleChain',
        'RetrievalQAWithSourcesChain', 'LLMMathChain', 'CombineDocsChain', 'RuleBasedRouter',
        'SequentialChain', 'LLMRouterChain', 'SimpleSequentialChain', 'LLMCheckerChain',
        'SQLDatabaseChain', 'LLMChain', 'APIChain', 'DalleGeneratorChain', 'MidJourneyPromptChain',
        'AutoGenChain', 'RetrievalChain', 'SeriesCharacterChain', 'RetrievalQA',
        'MultiPromptChain', 'ConversationChain', 'TimeTravelGuideChain'
    },
    'agents': {
        'LLMFunctionsAgent', 'AgentInitializer', 'ZeroShotAgent', 'SQLAgent', 'JsonAgent',
        'VectorStoreAgent', 'CSVAgent', 'ChatglmFunctionsAgent', 'VectorStoreRouterAgent'
    },
    'prompts': {
        'SystemMessagePromptTemplate', 'ChatPromptTemplate', 'ChatMessagePromptTemplate',
        'PromptTemplate', 'HumanMessagePromptTemplate', 'MessagesPlaceholder'
    },
    'llms': {
        'ChatWenxin', 'ChatQWen', 'HostQwenChat', 'ChatMinimaxAI', 'CTransformers', 'HostYuanChat',
        'HostChatGLM', 'SenseChat', 'AzureChatOpenAI', 'LlamaCpp', 'CustomLLMChat', 'ChatZhipuAI',
        'ProxyChatLLM', 'Cohere', 'HostQwen1_5Chat', 'OpenAI', 'HostLlama2Chat', 'Anthropic',
        'HostYiChat', 'VertexAI', 'HuggingFaceHub', 'ChatXunfeiAI', 'HostBaichuanChat',
        'ChatAnthropic', 'ChatOpenAI'
    },
    'memories': {
        'ConversationKGMemory', 'ConversationBufferWindowMemory', 'ConversationEntityMemory',
        'PostgresChatMessageHistory', 'VectorStoreRetrieverMemory', 'ConversationSummaryMemory',
        'MongoDBChatMessageHistory', 'ConversationBufferMemory'
    },
    'tools': {
        'Calculator', 'GoogleSearchResults', 'JsonListKeysTool', 'WikipediaQueryRun',
        'RequestsDeleteTool', 'QuerySQLDataBaseTool', 'PythonREPLTool', 'RequestsGetTool',
        'PythonFunction', 'InfoSQLDatabaseTool', 'RequestsPostTool', 'RequestsPatchTool',
        'ListSQLDatabaseTool', 'RequestsPutTool', 'GoogleSerperRun', 'BingSearchRun',
        'PythonFunctionTool', 'GoogleSearchRun', 'Search', 'JsonGetValueTool', 'PythonAstREPLTool',
        'JsonSpec', 'WolframAlphaQueryRun', 'Tool'
    },
    'toolkits': {
        'VectorStoreRouterToolkit', 'VectorStoreInfo', 'OpenAPIToolkit', 'VectorStoreToolkit',
        'JsonToolkit'
    },
    'wrappers': {'DallEAPIWrapper', 'SQLDatabase', 'TextRequestsWrapper'},
    'embeddings': {
        'WenxinEmbeddings', 'HuggingFaceEmbeddings', 'OpenAIEmbeddings', 'HostEmbeddings',
        'OpenAIProxyEmbedding', 'CohereEmbeddings', 'CustomHostEmbedding'
    },
    'vectorstores': {
        'ElasticKeywordsSearch', 'FAISS', 'MongoDBAtlasVectorSearch', 'Milvus', 'Weaviate',
        'Pinecone', 'Qdrant', 'Chroma', 'SupabaseVectorStore'
    },
    'documentloaders': {
        'EverNoteLoader', 'PyPDFLoader', 'UniversalKVLoader', 'SlackDirectoryLoader',
        'WebBaseLoader', 'CustomKVLoader', 'GitbookLoader', 'TextLoader', 'HNLoader',
        'IMSDbLoader', 'ElemUnstructuredLoaderV0', 'PyPDFDirectoryLoader', 'SRTLoader',
        'ReadTheDocsLoader', 'CSVLoader', 'CollegeConfidentialLoader', 'BSHTMLLoader',
        'DirectoryLoader', 'AZLyricsLoader', 'IFixitLoader', 'AirbyteJSONLoader',
        'FacebookChatLoader', 'GitLoader', 'NotionDirectoryLoader', 'CoNLLULoader',
        'GutenbergLoader', 'PDFWithSemanticLoader'
    },
    'textsplitters': {'CharacterTextSplitter', 'RecursiveCharacterTextSplitter'},
    'utilities': {
        'SearxSearchWrapper', 'WikipediaAPIWrapper', 'GoogleSearchAPIWrapper', 'SerpAPIWrapper',
        'WolframAlphaAPIWrapper', 'GoogleSerperAPIWrapper', 'BingSearchAPIWrapper'
    },
    'output_parsers': {'StructuredOutputParser', 'ResponseSchema'},
    'retrievers': {'MixEsVectorRetriever'},
    'input_output': {'VariableNode', 'InputNode', 'Report', 'InputFileNode'},
    'autogen_roles': {
        'AutoGenCoder', 'AutoGenUser', 'AutoGenGroupChatManager', 'AutoGenCustomRole',
        'AutoGenAssistant'
    },
    'custom_components': {'Data'}
}


def test_build():
    flow_id = '27abf101-050d-4cbc-9b3b-4e912fe14c87'
    headers = {}
    # headers = {
    #     'Cookie':
    #     'access_token_cookie=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ7XCJ1c2VyX25hbWVcIjogXCJhZG1pblwiLCBcInVzZXJfaWRcIjogMywgXCJyb2xlXCI6IFwiYWRtaW5cIn0iLCJpYXQiOjE3MDQ2OTU3NDQsIm5iZiI6MTcwNDY5NTc0NCwianRpIjoiMDBjNTFhMjUtNWIyNi00MGY4LWFiMTEtNzJhNTYxM2MzOTUyIiwiZXhwIjoxNzA0NzgyMTQ0LCJ0eXBlIjoiYWNjZXNzIiwiZnJlc2giOmZhbHNlfQ.zJxytrpW3J5zxLb9gzo7oImPaQlIqtZ9AE0g2Tx0RZY;'
    # }  # noqa
    # init
    init_url = 'http://127.0.0.1:7860/api/v1/build/init/' + flow_id
    inp = {'chat_id': '1232'}
    requests.post(init_url, json=inp, headers=headers)
    build_url = 'http://127.0.0.1:7860/api/v1/build/stream/' + flow_id

    resp = requests.get(url=build_url, headers=headers)
    resp


def verify_nodes():
    test_api = "http://127.0.0.1:3001/api/v1/all"
    res = requests.get(test_api).json()
    for k, v in res.get("data").items():
        last_version = ALL_NODE.get(k)
        if not last_version:
            print(f"add_new_cate {k}")
        else:
            for node in v.keys():
                if node not in last_version:
                    print(f"add_new_node {node}")

            for node in last_version:
                if node not in set(v.keys()):
                    print(f"miss node {node}")


#test_build()
verify_nodes()
