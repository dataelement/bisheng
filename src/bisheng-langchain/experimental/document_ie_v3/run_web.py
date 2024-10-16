import json
import os
import tarfile
import tempfile
from pathlib import Path
from typing import List, Tuple, Union

import yaml

os.environ["CUDA_VISIBLE_DEVICES"] = "5"
import gradio as gr
from document_extract import DocumentExtract
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
    _tar_file = tar_file.name
    if Path(_tar_file).name in tmp2example:
        _tempdir = tmp2example[Path(_tar_file).name]
    else:
        _tempdir = Path(tempfile.mkdtemp(dir=tmpdir))
        tmp2example[Path(_tar_file).name] = _tempdir
        with tarfile.open(_tar_file, 'r') as tar:
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


def llm_run(pdf_path, schema, is_few_shot=False, example_path=None):
    if is_few_shot:
        if not example_path:
            raise gr.Error('Error: Few-shot mode requires example file')
        else:
            validate_response = validate_tar(example_path)
            if not validate_response.status:
                raise gr.Error(validate_response.message)
            else:
                llm_kv_results = llm_client.predict_one_pdf(pdf_path.name, schema, validate_response.pairs)
                llm_kv_results = json.dumps(llm_kv_results, ensure_ascii=False, indent=2)
    else:
        pdf_path = pdf_path.name
        llm_kv_results = llm_client.predict_one_pdf(pdf_path, schema)
        llm_kv_results = json.dumps(llm_kv_results, ensure_ascii=False, indent=2)

    return llm_kv_results


if __name__ == '__main__':
    # config = json.load(open('./config.json'))
    with open('./config.yaml', 'r') as f:
        config = yaml.safe_load(f)

    model_path = config['model_path']
    adaptor_path = config.get('adaptor_path', None)
    idp_url = config['idp_url']
    web_host = config['web_host']
    web_port = config['web_port']
    generation_config = config['generation_config']
    spliter_config = config['spliter_config']

    llm_client = DocumentExtract(
        model_path=model_path,
        adaptor_path=adaptor_path,
        idp_url=idp_url,
        generation_config=generation_config,
        spliter_config=spliter_config,
    )

    with tempfile.TemporaryDirectory(dir='./tmp/extract_files') as tmpdir:
        with gr.Blocks(
            css='#margin-top {margin-top: 15px} #center {text-align: center;} #description {text-align: center}'
        ) as demo:
            with gr.Row(elem_id='center'):
                gr.Markdown('# ELLM v2 Demo')

            with gr.Row(elem_id='description'):
                gr.Markdown("""Information extraction for anything.""")

            with gr.Row():
                input_file = gr.components.File(label='FlowFile(仅支持图片和双层PDF)')
                schema = gr.Textbox(
                    label='抽取字段',
                    value='性别|姓名|护照号|国家码|国籍|有效期至|签发地点|签发机关|类型|出生日期|签发日期|标题|身份证号码|出生地点',
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

            demo.launch(server_name=web_host, server_port=web_port, share=True)
