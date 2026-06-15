from pymilvus import MilvusClient
import requests
from sqlmodel import Session, create_engine, text


def clean_es(host, user_name, auth, exist_knowledge, es_index):
    url = f'http://{host}/_stats'
    search_url = f'http://{host}/%s/_search'
    delete_by_query = f"http://{host}/%s/_delete_by_query"
    col = requests.get(url, auth=(user_name, auth)).json()
    for c in col.get('indices').keys():
        if c in es_index:
            print(c)
            pageNum = 0
            pageSize = 20
            delete_list = set()
            while True:
                print(pageNum)
                inp = {
                    "query": {
                        "bool": {
                            "must": [],
                            "must_not": [],
                            "should": []
                        }
                    },
                    "from": pageNum * pageSize,
                    "size": pageSize,
                    "sort": {},
                    "aggs": {},
                    "track_total_hits": True
                }
                query = search_url % c
                resp = requests.post(query, auth=(user_name, auth), json=inp).json()
                hists = resp.get("hits").get("hits")
                for hit in hists:
                    file_id = hit.get("_source").get("metadata").get("file_id")
                    if file_id not in exist_knowledge:
                        delete_list.add(hit.get("_id"))
                pageNum += 1
                if len(hists) != pageSize:
                    break
            delete_by_query_url = delete_by_query % c
            inp = {"query": {"bool": {"must": [{"ids": {"values": delete_list}}]}}}
            print(requests.post(delete_by_query_url, auth=(user_name, auth), json=inp).json())


def clean_milvus(host, exist_knowledge, collection_list):
    milvus_cli = MilvusClient(uri=host)
    collection = milvus_cli.list_collections()
    for col in collection:
        if col in collection_list:
            # 遍历条记录
            pageNum = 0
            delete_list = []
            while (True):
                records = milvus_cli.query(collection_name=col,
                                           output_fields=["pk", 'file_id'],
                                           filter='',
                                           offset=pageNum * 10,
                                           limit=10)
                pageNum += 1
                for record in records:
                    pk = record['pk']
                    file_id = record['file_id']
                    if file_id not in exist_knowledge:
                        delete_list.append(pk)

                if len(records != 10):
                    break
            milvus_cli.delete(collection_name=col, pks=delete_list)


def mysql_query(mysql_url):
    engine = create_engine(mysql_url, connect_args={}, pool_pre_ping=True)
    with Session(engine) as session:
        db_knowledgefile = session.exec(
            text('select id, collection_name, index_name from knowledgefile')).all()
        db_knowledge = session.exec(
            text('select collection_name, index_name from knowledge')).all()

        return {x[0]
                for x in db_knowledgefile}, {x[0]
                                             for x in db_knowledge}, {x[1]
                                                                      for x in db_knowledge}


mysql_url = 'mysql+pymysql://root:E1SkG0PaDMEPTAxY@192.168.106.116:3306/langflow?charset=utf8mb4'
exist_knowledge, collection_list, es_list = mysql_query(mysql_url)
# clean_es("192.168.106.116:9200",
#          'elastic',
#          auth="",
#          exist_knowledge=exist_knowledge,
#          es_index=es_list)
clean_milvus("http://192.168.106.109:19530",
             exist_knowledge=exist_knowledge,
             collection_list=collection_list)
