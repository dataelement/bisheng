import os
import tempfile
import gradio as gr
from bisheng_langchain.rag.qa_corpus.qa_generator import RagQAGenerator


tmpdir = '/home/public/rag_benchmark_v1.0/tmp'
if not os.path.exists(tmpdir):
    os.makedirs(tmpdir)

qa_gen_folder = '/home/public/rag_benchmark_v1.0/rag_qa_gen_demo'
if not os.path.exists(qa_gen_folder):
    os.makedirs(qa_gen_folder)
model_name = "gpt-4-0125-preview"
unstructured_api_url = "https://bisheng.dataelem.com/api/v1/etl4llm/predict"
generator = RagQAGenerator(corpus_folder='',
                           qa_gen_folder=qa_gen_folder, 
                           unstructured_api_url=unstructured_api_url, 
                           model_name=model_name)


def qa_gen_run(intput_file, gen_qa_num):
    gen_qa_num = int(gen_qa_num)
    file_path = intput_file.name
    output_file = generator.generate_qa_each_file(file_path, train_size=gen_qa_num)
    return output_file


with tempfile.TemporaryDirectory(dir=tmpdir) as tmpdir:
    with gr.Blocks(css='#margin-top {margin-top: 15px} #center {text-align: center;} #description {text-align: center}') as demo:
        with gr.Row(elem_id='center'):
            gr.Markdown('# Bisheng qa auto generation Demo')

        with gr.Row(elem_id = 'description'):
            gr.Markdown("""Qa generation for anything.""")

        with gr.Row():
            intput_file = gr.components.File(label='FlowFile')
            gen_qa_num = gr.Textbox(label='生成的问题数量', value=10, interactive=True, lines=2)

        with gr.Row():
            with gr.Column():
                btn0 = gr.Button('Run Qa Gen')
                out0 = gr.components.File(label='FlowFile')
                btn0.click(fn=qa_gen_run, inputs=[intput_file, gen_qa_num], outputs=out0)
                
        demo.launch(server_name='192.168.106.20', server_port=9118, share=True)