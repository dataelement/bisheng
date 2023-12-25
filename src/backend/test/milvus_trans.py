from bisheng_langchain.embeddings import HostEmbeddings
from bisheng_langchain.vectorstores import Milvus
from sqlmodel import Session, create_engine

params = {}
params['connection_args'] = {
    'host': '192.168.106.116',
    'port': '19530',
    'user': '',
    'password': '',
    'secure': False
}
params['documents'] = []
embedding = HostEmbeddings(model='multilingual-e5-large',
                           host_base_url='http://192.168.106.12:9001/v2.1/models')

database_url = 'mysql+pymysql://root:E1SkG0PaDMEPTAxY@192.168.106.116:3306/langflow?charset=utf8mb4'
engine = create_engine(database_url, connect_args={}, pool_pre_ping=True)
with Session(engine) as session:
    db_knowledge = session.exec('select id, collection_name, model from knowledge').all()
    for knowledge in db_knowledge:

        if knowledge[1].startswith('col'):
            params['collection_name'] = knowledge[1]
            cli = Milvus.from_documents(embedding=embedding, **params)
            li = cli.col.query(expr='file_id>1')
            pass
