# flake8: noqa: E501
import json
import os
import requests
import gradio as gr
import time
import tempfile
from document_extract import DocumentExtract

tmpdir = './tmp/extract_files'
if not os.path.exists(tmpdir):
  os.makedirs(tmpdir)


ellm_client = DocumentExtract(do_ellm=True, do_llm=False, llm_model_name='Qwen-72B-Chat-Int4')
llm_client = DocumentExtract(do_ellm=False, do_llm=True, llm_model_name='Qwen-72B-Chat-Int4')
ensemble_llm_first_client = DocumentExtract(do_ellm=True, do_llm=True,
    ensemble_method='llm_first', llm_model_name='Qwen-72B-Chat-Int4')
ensemble_ellm_first_client = DocumentExtract(do_ellm=True, do_llm=True,
    ensemble_method='ellm_first', llm_model_name='Qwen-72B-Chat-Int4')


def ellm_run(pdf_path, schema):
    pdf_path = pdf_path.name
    ellm_kv_results, llm_kv_results, final_kv_results = ellm_client.predict_one_pdf(pdf_path, schema)
    final_kv_results = json.dumps(final_kv_results, ensure_ascii=False, indent=2)
    return final_kv_results


def llm_run(pdf_path, schema):
    pdf_path = pdf_path.name
    ellm_kv_results, llm_kv_results, final_kv_results = llm_client.predict_one_pdf(pdf_path, schema)
    final_kv_results = json.dumps(final_kv_results, ensure_ascii=False, indent=2)
    return final_kv_results


def ensemble_llm_first_run(pdf_path, schema):
    pdf_path = pdf_path.name
    ellm_kv_results, llm_kv_results, final_kv_results = ensemble_llm_first_client.predict_one_pdf(pdf_path, schema)
    final_kv_results = json.dumps(final_kv_results, ensure_ascii=False, indent=2)
    return final_kv_results


def ensemble_ellm_first_run(pdf_path, schema):
    pdf_path = pdf_path.name
    ellm_kv_results, llm_kv_results, final_kv_results = ensemble_ellm_first_client.predict_one_pdf(pdf_path, schema)
    final_kv_results = json.dumps(final_kv_results, ensure_ascii=False, indent=2)
    return final_kv_results


with tempfile.TemporaryDirectory(dir='./tmp/extract_files') as tmpdir:
    with gr.Blocks(css='#margin-top {margin-top: 15px} #center {text-align: center;} #description {text-align: center}') as demo:
        with gr.Row(elem_id='center'):
            gr.Markdown('# Bisheng IE Demo')

        with gr.Row(elem_id = 'description'):
            gr.Markdown("""Information extraction for anything.""")

        with gr.Row():
            intput_file = gr.components.File(label='FlowFile')
            schema = gr.Textbox(label='抽取字段', value='买方|卖方|合同期限|结算条款|售后条款|合同总金额', interactive=True, lines=2)

        with gr.Row():
            with gr.Column():
                ellm_kv_results = gr.Textbox(label='ELLM抽取结果', value='', interactive=True, lines=1)
                btn0 = gr.Button('Run ELLM')
                btn0.click(fn=ellm_run, inputs=[intput_file, schema], outputs=ellm_kv_results)

            with gr.Column():
                llm_kv_results = gr.Textbox(label='LLM抽取结果', value='', interactive=True, lines=1)
                btn1 = gr.Button('Run LLM')
                btn1.click(fn=llm_run, inputs=[intput_file, schema], outputs=llm_kv_results)

        with gr.Row():
            with gr.Column():
                ensemble2_kv_results = gr.Textbox(label='ensemble_ellm_first抽取结果', value='', interactive=True, lines=1)
                btn3 = gr.Button('Run ensemble_ellm_first')
                btn3.click(fn=ensemble_ellm_first_run, inputs=[intput_file, schema], outputs=ensemble2_kv_results)

            with gr.Column():
                ensemble1_kv_results = gr.Textbox(label='ensemble_llm_first抽取结果', value='', interactive=True, lines=1)
                btn2 = gr.Button('Run ensemble_llm_first')
                btn2.click(fn=ensemble_llm_first_run, inputs=[intput_file, schema], outputs=ensemble1_kv_results)

        demo.launch(server_name='192.168.106.12', server_port=9118, share=True)

