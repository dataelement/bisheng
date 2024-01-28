import json

import pandas as pd
from langchain.chains.question_answering import load_qa_chain
from langchain.chat_models import ChatOpenAI
from langchain.schema import Document
from loguru import logger

LLM = ChatOpenAI(model="gpt-4-1106-preview", temperature=0.0)


def get_answer(data_path, output_path=None):
    df = pd.read_excel(data_path, sheet_name='Sheet2')

    all_docs_path = '../data/all_split_docs.json'
    with open(all_docs_path, 'r') as f:
        all_docs = json.load(f)

    match_files = set()
    qa_chain = load_qa_chain(llm=LLM, chain_type="stuff", verbose=True)
    for i, row in df.iterrows():
        filename = row['文件名']
        docs = all_docs[filename]
        all_texts = ''.join([doc['page_content'] for doc in docs])
        doc_token_len = len(all_texts)
        if 0 < doc_token_len < 8000:
            input_docs = [Document(page_content=all_texts)]
            question = row['问题']
            ans = qa_chain({"input_documents": input_docs, "question": question}, return_only_outputs=True)
            df.iloc[i, 'rag_answer'] = ans
            # match_files.add((filename, doc_token_len))
        print(len(match_files))

    # 保留df中文件名在match_files中的行
    short_doc_df = df[df['文件名'].isin({x[0] for x in match_files})]
    short_doc_df.to_excel('../data/short_doc_df.xlsx', index=False)


if __name__ == '__main__':
    gpt4_benchmark_path = '../data/gpt-4.xlsx'
    get_answer(gpt4_benchmark_path)
