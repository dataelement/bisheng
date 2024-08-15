import json
import os
import tempfile
from pathlib import Path

import gradio as gr
import pandas as pd
import yaml
from retrieval_v2 import LlmBasedLayerwiseReranker, VectorSearch
from sentence_transformers import SentenceTransformer, util

tmpdir = './tmp/query_retrieval'
Path(tmpdir).mkdir(parents=True, exist_ok=True)


config_file = './config.yaml'
with open(config_file) as f:
    CONFIG = yaml.load(f, Loader=yaml.FullLoader)

EMBEDDING_MODEL = SentenceTransformer(
    model_name_or_path=CONFIG['vector_store']['embedding']['model_path'],
)
EMBEDDING_MODEL.to(CONFIG['vector_store']['embedding']['device'])
RERANK_MODEL = LlmBasedLayerwiseReranker(
    model_path=CONFIG['reranker']['model_path'],
    device=CONFIG['reranker']['device'],
)


def build_vector_store(input_file: str):
    df = pd.read_csv(input_file.name)
    global VectorStore
    VectorStore = VectorSearch(
        embedding_model=EMBEDDING_MODEL,
        store_name=CONFIG['vector_store']['store_name'],
        docs=df['Question'].to_list(),
        drop_old_cache=True,
    )


def predict(query: str):
    result = VectorStore.search(query, add_instruction=False, topk=10, threshold=0.7)
    if len(result) == 0:
        return "没有找到相关问题"
    else:
        rerank_score, rerank_inds = RERANK_MODEL.rerank([[query, r] for r in result])
        return result[rerank_inds]


with tempfile.TemporaryDirectory(dir=tmpdir) as tmpdirname:
    with gr.Blocks(
        css='#margin-top {margin-top: 15px} #center {text-align: center;} #description {text-align: center}'
    ) as demo:
        with gr.Row(elem_id='center'):
            gr.Markdown('## Query Retrieval')

        with gr.Row(elem_id='description'):
            gr.Markdown('This demo retrieves similar queries from a collection of queries.')

        with gr.Row():
            with gr.Column():
                input_file = gr.components.File(label='Upload a csv file, column name must be "Question"')
                btn1 = gr.Button('Step1: Submit')
                btn1.click(fn=build_vector_store, inputs=[input_file])

        with gr.Row():
            with gr.Column():
                query = gr.Textbox(label='Query', elem_id='query')
                btn2 = gr.Button('Step2: Search')
            with gr.Column():
                output = gr.Textbox(label='Result', elem_id='result')
                btn2.click(fn=predict, inputs=[query], outputs=[output])

        demo.launch(server_name=CONFIG['web_host'], server_port=CONFIG['web_port'], share=True)
