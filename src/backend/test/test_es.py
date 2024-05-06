import os
import sys
from langchain_elasticsearch import ElasticsearchStore
from bisheng_langchain.vectorstores import Milvus

parent_dir = os.path.dirname(os.path.abspath(__file__)).replace('test', '')
sys.path.append(parent_dir)
os.environ['config'] = os.path.join(parent_dir, 'bisheng/config.dev.yaml')
from bisheng.interface.embeddings.custom import FakeEmbedding

embedding = FakeEmbedding()


def data_migrate(host_milvus: str, target_es: str, col_name: str):
    params = {}
    params['connection_args'] = {
        'host': host_milvus,
        'port': '19530',
        'secure': False,
        'timeout': 3
    }
    params['documents'] = []
    params['collection_name'] = col_name

    from_milvus = Milvus.from_documents(embedding=embedding, **params)
    vectorstore = ElasticsearchStore(embedding=embedding,
                                     index_name=col_name,
                                     es_url=target_es,
                                     es_user="elastic",
                                     es_password="oSGL-zVvZ5P3Tm7qkDLC")
    fields = [s.name for s in from_milvus.col.schema.fields if s.name != 'pk']
    pks = from_milvus.col.query(expr='file_id>1')
    pk_len = len(pks)
    print(f"milvus_len={pk_len}")
    if pk_len == 0:
        return
    li = []
    batch_size = 500
    for i in range(0, pk_len, batch_size):
        print(i)
        end = min(i + batch_size, pk_len)
        pk_ids = [str(pk.get('pk')) for pk in pks[i:end]]
        pk_with_fields = from_milvus.col.query(f"pk in [{','.join(pk_ids)}]", output_fields=fields)

        text_embedding = [(data.pop("text"), data.pop("vector")) for data in pk_with_fields]
        print(vectorstore.add_embeddings(text_embeddings=text_embedding, metadatas=pk_with_fields))


def data_migrage_milvus(host_milvus: str, target_host: str, col_name):
    params = {}
    params['connection_args'] = {
        'host': host_milvus,
        'port': '19530',
        'secure': False,
        'timeout': 3
    }
    params['documents'] = []
    params['collection_name'] = col_name
    from_milvus = Milvus.from_documents(embedding=embedding, **params)
    params['connection_args']['host'] = target_host

    target_milvus = Milvus.from_documents(embedding=embedding, **params)
    fields = [s.name for s in from_milvus.col.schema.fields if s.name != 'pk']
    pks = from_milvus.col.query(expr='file_id>1')
    pk_len = len(pks)
    print(f"milvus_len={pk_len}")
    if pk_len == 0:
        return

    batch_size = 500
    target_fields = [s.name for s in target_milvus.col.schema.fields if s.name != 'pk']
    for i in range(0, pk_len, batch_size):
        print(i)
        end = min(i + batch_size, pk_len)
        pk_ids = [str(pk.get('pk')) for pk in pks[i:end]]
        # [{text: vector...}]
        pk_with_fields = from_milvus.col.query(f"pk in [{','.join(pk_ids)}]", output_fields=fields)
        insert_list = []
        for field in target_fields:
            insert_list.append([x.get(field) for x in pk_with_fields])
        res = target_milvus.col.insert(pk_with_fields, timeout=100)
        print(f"batch_insert_donw res={res}")


data_migrate("192.168.106.109", "http://192.168.106.115:9200",
             'partition_text_embedding_ada_002_knowledge_1')

data_migrage_milvus("192.168.106.109", "192.168.106.120",
                    'partition_text_embedding_ada_002_knowledge_1')
