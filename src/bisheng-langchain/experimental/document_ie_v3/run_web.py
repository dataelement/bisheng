import json
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple, Union

import gradio as gr
from document_extract import DocumentExtract
from prompt import EXAMPLE_FORMAT
from pydantic import BaseModel

tmpdir = './tmp/extract_files'
if not os.path.exists(tmpdir):
    os.makedirs(tmpdir)


class ValidateTarResponse(BaseModel):
    status: bool
    message: str
    pairs: Union[None, List[Tuple[Path, Path]]]


global tmp2example
tmp2example = {}


def validate_tar(tar_file) -> ValidateTarResponse:
    if Path(tar_file).name in tmp2example:
        _tempdir = tmp2example[Path(tar_file).name]
    else:
        _tempdir = Path(tempfile.mkdtemp(dir=tmpdir))
        tmp2example[Path(tar_file).name] = _tempdir
        with tarfile.open(tar_file.name, 'r') as tar:
            tar.extractall(_tempdir)
    label_list = [i for i in _tempdir.glob('**/[!.]*.json')]
    all_files = [i for i in _tempdir.glob('**/[!.]*')]

    pairs = []
    for label_file in label_list:
        with open(label_file, 'r') as f:
            try:
                json.load(f)
            except json.JSONDecodeError:
                return ValidateTarResponse(
                    status=False,
                    message='Error: Invalid json file',
                    pairs=None,
                )

        try:
            prefix = label_file.stem
            img_file = [i for i in all_files if i.stem == prefix and i.suffix != '.json'][0]
        except StopIteration:
            return ValidateTarResponse(
                status=False,
                message='Error: No valid pair found',
                pairs=None,
            )

        pairs.append((img_file, label_file))

        if len(pairs) > 1:
            break

    if len(pairs) == 0:
        return ValidateTarResponse(status=False, message='Error: No valid pair found', pairs=None)

    return ValidateTarResponse(status=True, message='Success', pairs=pairs)


def llm_run(pdf_path, schema, is_few_shot, example_path):
    if is_few_shot:
        validate_response = validate_tar(example_path)
        if not validate_response.status:
            gr.Error(validate_response.message)
        else:
            llm_kv_results = llm_client.predict_one_pdf(pdf_path.name, schema, validate_response.pairs)
            llm_kv_results = json.dumps(llm_kv_results, ensure_ascii=False, indent=2)
    else:
        pdf_path = pdf_path.name
        llm_kv_results = llm_client.predict_one_pdf(pdf_path, schema)
        llm_kv_results = json.dumps(llm_kv_results, ensure_ascii=False, indent=2)

    return llm_kv_results


if __name__ == '__main__':
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

    with tempfile.TemporaryDirectory(dir='./tmp/extract_files') as tmpdir:
        with gr.Blocks(
            css='#margin-top {margin-top: 15px} #center {text-align: center;} #description {text-align: center}'
        ) as demo:
            with gr.Row(elem_id='center'):
                gr.Markdown('# Bisheng IE Demo')

            with gr.Row(elem_id='description'):
                gr.Markdown("""Information extraction for anything.""")

            with gr.Row():
                input_file = gr.components.File(label='FlowFile')
                schema = gr.Textbox(
                    label='抽取字段',
                    value='姓名|工作年限|职务|标题|收入|身份证号码|学历',
                    interactive=True,
                    lines=2,
                )
            with gr.Row():
                with gr.Column():
                    is_few_shot = gr.Checkbox(label='Few-shot')
                with gr.Column():
                    btn1 = gr.Button('Run LLM')
            with gr.Row():
                with gr.Column():
                    input_example = gr.components.File(label='示例文件tar包')
                with gr.Column():
                    llm_kv_results = gr.Textbox(label='LLM抽取结果', value='', interactive=True, lines=1)

                btn1.click(fn=llm_run, inputs=[input_file, schema, is_few_shot, input_example], outputs=llm_kv_results)

            demo.launch(server_name=web_host, server_port=7777, share=True)
