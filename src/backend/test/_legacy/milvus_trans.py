import json

import requests
from bisheng_langchain.embeddings import HostEmbeddings
from bisheng_langchain.vectorstores import Milvus
from pymilvus import Collection, MilvusClient, MilvusException
from sqlmodel import Session, create_engine, text

params = {}
params['connection_args'] = {
    'host': '192.168.106.116',
    'port': '19530',
    'user': '',
    'password': '',
    'secure': False,
    'timeout': 3
}
params['documents'] = []
embedding = HostEmbeddings(model='multilingual-e5-large',
                           host_base_url='http://192.168.106.12:9001/v2.1/models')

database_url = 'mysql+pymysql://root:E1SkG0PaDMEPTAxY@192.168.106.116:3306/langflow?charset=utf8mb4'
engine = create_engine(database_url, connect_args={}, pool_pre_ping=True)


def milvus_trans():
    params['collection_name'] = 'partition_text_embedding_ada_002_knowledge_1'
    openai_target = Milvus.from_documents(embedding=embedding, **params)
    print("ls")
    params['collection_name'] = 'partition_multilinguale5large_knowledge_1'
    host_targe = Milvus.from_documents(embedding=embedding, **params)
    with Session(engine) as session:
        db_knowledge = session.exec(
            text('select id, collection_name, model, index_name from knowledge')).all()
        for knowledge in db_knowledge:
            # if not knowledge[1].startswith('col'):
            #     if knowledge[3].startswith('col'):
            #         # 迁移完
            #         print(f"drop id={knowledge}")
            #         params['collection_name'] = knowledge[3]
            #         cli = Milvus.from_documents(embedding=embedding, **params)
            #         if cli.col:
            #             cli.col.drop()
            #         time.sleep(1)
            #         continue
            if knowledge[1].startswith('col'):
                print(f'deal id={knowledge[0]} model={knowledge[2]} col={knowledge[1]}')
                params['collection_name'] = knowledge[1]
                cli = Milvus.from_documents(embedding=embedding, **params)
                if not cli.col:
                    print(f'escape id={knowledge[0]} col={knowledge[1]}')
                    index_name = knowledge[1]
                    col_name = f'partition_{knowledge[2]}_knowledge_1'.replace('-', '')
                    sql = 'update knowledge set collection_name="%s", index_name="%s" where id=%d' % (
                        col_name, index_name, knowledge[0])
                    session.exec(sql)
                    session.commit()
                    continue
                fields = [s.name for s in cli.col.schema.fields if s.name != 'pk']
                print(fields)
                pks = cli.col.query(expr='file_id>1')
                pk_len = len(pks)
                if pk_len == 0:
                    continue
                li = []
                batch_size = 500
                for i in range(0, pk_len, batch_size):
                    end = min(i + batch_size, pk_len)
                    pk_ids = [str(pk.get('pk')) for pk in pks[i:end]]
                    pk_with_fields = cli.col.query(f"pk in [{','.join(pk_ids)}]",
                                                   output_fields=fields)
                    li.extend(pk_with_fields)
                if knowledge[2] == 'text-embedding-ada-002':
                    target = openai_target
                elif knowledge[2] == 'multilingual-e5-large':
                    target = host_targe
                else:
                    continue

                insert_fields = [s.name for s in target.col.schema.fields if s.name != 'pk']
                insert_dict = {
                    'text': [],
                    'vector': [],
                    'file_id': [],
                    'knowledge_id': [],
                    'page': [],
                    'source': [],
                    'bbox': [],
                    'extra': []
                }
                for data in li:
                    insert_dict.get('text').append(data.get('text'))
                    insert_dict.get('vector').append(data.get('vector'))
                    insert_dict.get('file_id').append(data.get('file_id'))
                    insert_dict.get('knowledge_id').append(f'{knowledge[0]}')

                    if 'bbox' in fields:
                        if data.get('bbox'):
                            insert_dict.get('bbox').append(
                                '{"chunk_bboxes":%s}' %
                                (json.loads(data.get('bbox')).get('chunk_bboxes')))
                            if json.loads(data.get('bbox')).get('source'):
                                insert_dict.get('source').append(
                                    json.loads(data.get('bbox')).get('source'))
                            if json.loads(data.get('bbox')).get('chunk_bboxes')[0].get('page'):
                                insert_dict.get('page').append(
                                    json.loads(
                                        data.get('bbox')).get('chunk_bboxes')[0].get('page'))
                        else:
                            insert_dict.get('bbox').append('')
                    else:
                        insert_dict.get('bbox').append('')
                    if 'source' in fields:
                        insert_dict.get('source').append(data.get('source'))
                    if len(insert_dict.get('source')) != len(insert_dict.get('bbox')):
                        insert_dict.get('source').append('')
                    if 'page' in fields:
                        insert_dict.get('page').append(data.get('page') if data.get('page') else 1)

                    insert_dict.get('extra').append('')

                total_count = len(li)
                batch_size = 1000
                for i in range(0, total_count, batch_size):
                    # Grab end index
                    end = min(i + batch_size, total_count)
                    # Convert dict to list of lists batch for insertion
                    insert_list = [insert_dict[x][i:end] for x in insert_fields]
                    # Insert into the collection.
                try:
                    res: Collection
                    res = target.col.insert(insert_list, timeout=100)
                    print(res)
                except MilvusException as e:
                    print('Failed to insert batch starting at entity: %s/%s', i, total_count)
                    raise e

                index_name = knowledge[1]
                col_name = f'partition_{knowledge[2]}_knowledge_1'.replace('-', '')
                sql = 'update knowledge set collection_name="%s", index_name="%s" where id=%d' % (
                    col_name, index_name, knowledge[0])
                session.exec(sql)
                session.commit()
                print(f'deal_done id={knowledge[0]} index={index_name}')
                cli.col.drop()
                pass


from pymilvus import Collection, MilvusClient, MilvusException

import json

import requests


def milvus_clean():
    milvus_cli = MilvusClient(uri='http://192.168.106.109:19530')

    collection = milvus_cli.list_collections()
    for col in collection:
        if col.startswith('tmp'):
            print(col)
            # collection_col = Collection(col, using=milvus_cli._using)
            milvus_cli.drop_collection(col)

            # try:
            #     collection_col.release(timeout=1)
            # except Exception:
            #     continue


def elastic_clean():
    url = 'http://192.168.106.109:9200/_stats'
    user_name = 'elastic'
    auth = 'MBDsrs5O_zHCE+12na3f'
    del_url = 'http://192.168.106.109:9200/%s'
    col = requests.get(url, auth=(user_name, auth)).json()
    for c in col.get('indices').keys():
        if c.startswith('tmp'):
            print(c)
            x = requests.delete(del_url % c, auth=(user_name, auth))
        elif col.get('indices').get(c).get('primaries').get('docs').get('count') == 0:
            print(c)
            x = requests.delete(del_url % c, auth=(user_name, auth))
            print(x)


milvus_clean()
# elastic_clean()
# milvus_trans()
