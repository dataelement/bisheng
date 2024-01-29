import json
from pathlib import Path

import httpx
import pandas as pd
from bisheng_langchain.chat_models import HostQwenChat
from langchain.chains.question_answering import load_qa_chain
from langchain.chat_models import ChatOpenAI
from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from loguru import logger

LLM = ChatOpenAI(
    model="gpt-3.5-turbo-1106",
    temperature=0.0,
    http_client=httpx.Client(proxies=f"http://118.195.232.223:39995"),
    timeout=3000,
)

LLM = HostQwenChat(
    model='Qwen-14B-Chat',
    host_base_url='http://34.142.140.180:7001/v2.1/models',
    temperature=0.0,
    request_timeout=1000,
)


def get_answer_for_8k(data_path, benchamrk_model, output_path=None):
    """
    8k以下的文档直接用llm回答问题

    Args:
        data_path: _description_
        benchamrk_model: _description_
        output_path: _description_. Defaults to None.
    """
    df = pd.read_excel(data_path, sheet_name=benchamrk_model)
    df.dropna(subset=['GT'], inplace=True)

    all_docs_path = '../data/all_split_docs.json'
    with open(all_docs_path, 'r') as f:
        all_docs = json.load(f)

    match_files = list()
    qa_chain = load_qa_chain(llm=LLM, chain_type="stuff", verbose=False)
    for i, row in df.iterrows():
        filename = row['文件名']

        docs = all_docs[filename]
        all_texts = ''.join([doc['page_content'] for doc in docs])
        doc_token_len = len(all_texts)

        # print(f'filename: {filename}, doc_token_len: {doc_token_len}')
        if 0 < doc_token_len < 8000:
            input_docs = [Document(page_content=all_texts)]
            question = row['问题改写']  # 改写后的问题
            try:
                ans = qa_chain({"input_documents": input_docs, "question": question}, return_only_outputs=True)
                answer = ans['output_text']
            except Exception as e:
                print(e)
                answer = str(e)
            print(f'question: {question}, answer: {answer}')
            df.loc[i, 'rag_answer_without_rtvl'] = answer
            match_files.append(filename)
            # break

    print(f'question num: {len(match_files)}')
    print(f'file num: {len(set(match_files))}')

    # 保留df中文件名在match_files中的行
    short_doc_df = df[df['文件名'].isin(match_files)]
    short_doc_df.to_excel(Path(output_path) / f'short_doc_8k_{benchamrk_model}.xlsx', index=False)


def get_answer_for_16k(data_path, benchamrk_model, output_path=None):
    """
    [8k, 16k) 使用reduce的方式回答问题

    Args:
        data_path: _description_
        benchamrk_model: _description_
        output_path: _description_. Defaults to None.
    """
    df = pd.read_excel(data_path, sheet_name=benchamrk_model)
    df.dropna(subset=['GT'], inplace=True)

    all_docs_path = '../data/all_split_docs.json'
    with open(all_docs_path, 'r') as f:
        all_docs = json.load(f)

    match_files = list()
    qa_chain = load_qa_chain(llm=LLM, chain_type="refine", verbose=True)
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=8000, chunk_overlap=200, separators=['\n', ' ', ''])
    for i, row in df.iterrows():
        filename = row['文件名']

        docs = all_docs[filename]
        all_texts = ''.join([doc['page_content'] for doc in docs])
        doc_token_len = len(all_texts)

        # print(f'filename: {filename}, doc_token_len: {doc_token_len}')
        if 8000 <= doc_token_len < 16000:
            split_docs = text_splitter.split_documents([Document(page_content=all_texts)])

            question = row['问题改写']  # 改写后的问题
            try:
                ans = qa_chain({"input_documents": split_docs, "question": question}, return_only_outputs=True)
                answer = ans['output_text']
            except Exception as e:
                print(e)
                answer = str(e)
            print(f'question: {question}, answer: {answer}')
            df.loc[i, 'rag_answer_without_rtvl'] = answer
            match_files.append(filename)
            # break

    print(f'question num: {len(match_files)}')
    print(f'file num: {len(set(match_files))}')

    # 保留df中文件名在match_files中的行
    short_doc_df = df[df['文件名'].isin(match_files)]
    short_doc_df.to_excel(Path(output_path) / f'short_doc_16k_{benchamrk_model}.xlsx', index=False)


if __name__ == '__main__':
    gpt4_benchmark_path = '../data/benchmark_v1.0.xlsx'
    output_path = '../data'
    get_answer_for_8k(gpt4_benchmark_path, 'qwen14b', output_path)
