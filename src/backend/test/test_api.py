from bisheng import load_flow_from_json

TWEAKS = {
    'PyPDFLoader-RJlDA': {},
    'InputFileNode-hikjJ': {},
    'InputNode-keWk3': {},
    'Milvus-VzZtx': {},
    'RetrievalQA-Y4e1R': {},
    'CombineDocsChain-qrRE4': {},
    'RecursiveCharacterTextSplitter-C6YSc': {},
    'ProxyChatLLM-oWqpn': {},
    'HostEmbeddings-EJq6w': {}
}
flow = load_flow_from_json('⭐️ PDF文档摘要-zxf.json', tweaks=TWEAKS)
# Now you can use it like any chain
inputs = {'query': '', 'id': 'RetrievalQA-Y4e1R'}
flow(inputs)
