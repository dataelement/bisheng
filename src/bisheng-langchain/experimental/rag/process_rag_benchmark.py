import os
import json
import shutil
import pandas as pd
from tqdm import tqdm
from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter
from langchain.vectorstores import Milvus
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.chat_models import ChatOpenAI
from bisheng_langchain.vectorstores import ElasticKeywordsSearch
from bisheng_langchain.retrievers import MixEsVectorRetriever
from langchain.chains.question_answering import load_qa_chain

embeddings = OpenAIEmbeddings(model="text-embedding-ada-002")
llm = ChatOpenAI(model="gpt-4-1106-preview", temperature=0.0)

file_types = {
    'doc': 'doc',
    'docx': 'doc',
    'ppt': 'ppt',
    'pptx': 'ppt',
    'pdf': 'pdf',
    'jpg': 'img',
    'png': 'img',
    'jpeg': 'img',
    'bmp': 'img',
    'gif': 'img',
    'txt': 'txt',
    'xls': 'xls',
    'xlsx': 'xls',
    'csv': 'csv',
    'md': 'md',
}


def process_rag_benchmark(data_dir, save_dir):
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    else:
        shutil.rmtree(save_dir)
        os.makedirs(save_dir)
    
    file_indexes = os.listdir(data_dir)
    all_questions_info = list()
    type_num = dict()
    file2collection = dict()
    file_num = 0
    for file_index in file_indexes:
        file_index_dir = os.path.join(data_dir, file_index)
        message = os.path.join(file_index_dir, 'message.txt')
        if not os.path.exists(message):
            continue
        
        with open(message, 'r') as f:
            for line in f.readlines():
                line = line.strip()
                try:
                    question, file_name = line.split('@')
                except:
                    print('error line: {}'.format(line))
                    continue

                file_path = os.path.join(file_index_dir, file_name)
                if not os.path.exists(file_path):
                    raise ValueError('file not exists: {}'.format(file_path))
                
                type = file_name.split('.')[-1]
                if type not in file_types:
                    raise ValueError('file type not supported: {}'.format(type))

                save_file_path = os.path.join(save_dir, file_index + '_' + file_name)
                if not os.path.exists(save_file_path):
                    type_num[file_types[type]] = type_num.get(file_types[type], 0) + 1
                    shutil.copy(file_path, save_file_path)

                if file_index + '_' + file_name not in file2collection:
                    collection_name = f'rag_benchmark_v0_file_{file_num}'
                    file2collection[file_index + '_' + file_name] = collection_name
                    file_num += 1

                question_info = dict()
                question_info['问题'] = question
                question_info['问题类型'] = ''
                question_info['文件名'] = file_index + '_' + file_name
                question_info['文件类型'] = file_types[type]
                question_info['知识库名'] = file2collection[file_index + '_' + file_name]
                all_questions_info.append(question_info)

    # save excel
    df = pd.DataFrame(all_questions_info)
    df.to_excel(os.path.join(save_dir, 'questions_info.xlsx'), index=False)
    with open(os.path.join(save_dir, 'file2collection.json'), 'w') as f:
        json.dump(file2collection, f, indent=2, ensure_ascii=False)
    print('type_num: {}'.format(type_num))
    print('total file num', file_num)


def data_loader(data_folder):
    pdf_files = [os.path.join(data_folder, i) for i in os.listdir(data_folder) if i.endswith('.pdf')]
    file2collection_file = os.path.join(data_folder, 'file2collection.json')
    with open(file2collection_file, 'r') as f:
        file2collection = json.load(f)

    for file_path in tqdm(pdf_files):
        file_name = os.path.basename(file_path)
        # loader = PyPDFLoader(file_path)
        loader = ElemUnstructuredLoader(file_name=file_name,
                                        file_path=file_path,
                                        unstructured_api_url="https://bisheng.dataelem.com/api/v1/etl4llm/predict")
        documents = loader.load()
        print('documents:', len(documents))

        # text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        text_splitter = ElemCharacterTextSplitter(chunk_size=500,
                                                  chunk_overlap=50,
                                                  separators=['\n\n', '\n', ' ', ''])
        split_docs = text_splitter.split_documents(documents)
        for split_doc in split_docs:
            split_doc.metadata.pop('chunk_bboxes')
        print('split_docs:', len(split_docs))

        MILVUS_HOST = '192.168.106.116'
        MILVUS_PORT = '19530'
        collection_name = file2collection[file_name] + '_milvus'
        vector_store = Milvus.from_documents(
            split_docs,
            embedding=embeddings,
            collection_name=collection_name,
            drop_old=True,
            connection_args={"host": MILVUS_HOST, "port": MILVUS_PORT}
        )

        ssl_verify = {'basic_auth': ("elastic", "oSGL-zVvZ5P3Tm7qkDLC")}
        index_name = file2collection[file_name] + '_es'
        es_store = ElasticKeywordsSearch.from_documents(
            split_docs, 
            embeddings, 
            elasticsearch_url="http://192.168.106.116:9200",
            index_name=index_name,
            ssl_verify=ssl_verify
        )


def get_answer(data_dir):
    excel_file = os.path.join(data_dir, 'questions_info.xlsx')

    df = pd.read_excel(excel_file)
    all_questions_info = list()
    # 遍历每一行
    for index, row in df.iterrows():
        # 遍历每一列
        question_info = dict()
        for column in df.columns:
            value = row[column]
            question_info[column] = value
            # print(f"Row {index}, Column {column} has value {value}")
        all_questions_info.append(question_info)
    
    qa_chain = load_qa_chain(llm=llm, chain_type="stuff", verbose=False)
    for questions_info in tqdm(all_questions_info):
        question = questions_info['问题']
        file_type = questions_info['文件类型']
        collection_name = questions_info['知识库名']
        
        # only consider pdf
        if file_type == 'pdf':
            # get answer from milvus
            MILVUS_HOST = '192.168.106.116'
            MILVUS_PORT = '19530'
            vector_store = Milvus(
                embedding_function=embeddings,
                collection_name=collection_name + "_milvus",
                connection_args={"host": MILVUS_HOST, "port": MILVUS_PORT}
            )
            vector_retriever = vector_store.as_retriever(
                search_type="similarity", search_kwargs={"k": 10})

            ssl_verify = {'basic_auth': ("elastic", "oSGL-zVvZ5P3Tm7qkDLC")}
            es_store = ElasticKeywordsSearch(
                elasticsearch_url="http://192.168.106.116:9200",
                index_name=collection_name + "_es",
                ssl_verify=ssl_verify)
            keyword_retriever = es_store.as_retriever(
                search_type="similarity", search_kwargs={"k": 10})

            combine_strategy = 'mix'
            es_vector_retriever = MixEsVectorRetriever(vector_retriever=vector_retriever,
                                                       keyword_retriever=keyword_retriever,
                                                       combine_strategy=combine_strategy)
            docs = es_vector_retriever.get_relevant_documents(question)
            ans = qa_chain({"input_documents": docs, "question": question}, 
                           return_only_outputs=True)
            print('ans:', ans, 'question:', question)
            questions_info['rag_answer'] = ans['output_text']
        else:
            questions_info['rag_answer'] = ''
    
    df = pd.DataFrame(all_questions_info)
    df.to_excel(os.path.join(save_dir, 'questions_info_with_answer.xlsx'), index=False)


if __name__ == '__main__':
    data_dir = '/home/gulixin/workspace/datasets/rag_benchmark'
    save_dir = '/home/gulixin/workspace/datasets/rag_benchmark_processed'
    # process_rag_benchmark(data_dir, save_dir)
    # data_loader(save_dir)
    get_answer(save_dir)
