# flake8: noqa: E501
import json
import os
import tempfile

import gradio as gr
from document_extract import DocumentExtract

tmpdir = './tmp/extract_files'
if not os.path.exists(tmpdir):
    os.makedirs(tmpdir)

config = json.load(open('./config.json'))

unstructured_api_url = config['unstructured_api_url']
model_path = config['model_path']
idp_url = config['idp_url']
server_type = config['server_type']
web_host = config['web_host']
web_port = config['web_port']


llm_client = DocumentExtract(
    unstructured_api_url=unstructured_api_url,
    model_path=model_path,
    idp_url=idp_url,
)


def llm_run(pdf_path, schema):
    pdf_path = pdf_path.name
    llm_kv_results = llm_client.predict_one_pdf(pdf_path, schema)
    llm_kv_results = json.dumps(llm_kv_results, ensure_ascii=False, indent=2)
    return llm_kv_results


with tempfile.TemporaryDirectory(dir='./tmp/extract_files') as tmpdir:
    with gr.Blocks(
        css='#margin-top {margin-top: 15px} #center {text-align: center;} #description {text-align: center}'
    ) as demo:
        with gr.Row(elem_id='center'):
            gr.Markdown('# Bisheng IE Demo')

        with gr.Row(elem_id='description'):
            gr.Markdown("""Information extraction for anything.""")

        with gr.Row():
            intput_file = gr.components.File(label='FlowFile')
            schema = gr.Textbox(
                label='抽取字段', value='买方|卖方|合同期限|结算条款|售后条款|合同总金额', interactive=True, lines=2
            )

        with gr.Row():
            with gr.Column():
                # system_message = gr.Textbox(label='大模型信息抽取', value=system_template, interactive=True, lines=2)
                btn1 = gr.Button('Run LLM')

            with gr.Column():
                llm_kv_results = gr.Textbox(label='LLM抽取结果', value='', interactive=True, lines=1)
            btn1.click(fn=llm_run, inputs=[intput_file, schema], outputs=llm_kv_results)

        demo.launch(server_name=web_host, server_port=7777, share=True)
