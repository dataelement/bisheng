# flake8: noqa: E501
import json
import os
import requests
import gradio as gr
import time


tmpdir = './tmp/autoplan_data'
if not os.path.exists(tmpdir):
  os.makedirs(tmpdir)


def run(skill, task_desc, global_params):
    task_desc = task_desc.replace('\n', '')
    global_params = global_params.replace('，', ',')
    data = {'skill': skill, 'task_desc': task_desc, 'global_params': global_params}
    res = requests.post('http://{}:{}/auto_planning_v1'.format('192.168.106.12', 9118), json=data).text
    agent_graph = eval(res)['data']

    flow_time = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    output_file = os.path.join(tmpdir, skill + '_' + flow_time + '.json')
    with open(output_file, 'w') as f:
        json.dump(agent_graph, f, ensure_ascii=False, indent=2)

    return output_file


with gr.Blocks(css='#margin-top {margin-top: 15px} #center {text-align: center;} #description {text-align: center}') as demo:
    with gr.Row(elem_id='center'):
        gr.Markdown('# AutoPlanning Demo')

    with gr.Row(elem_id = 'description'):
        gr.Markdown("""To run autoplaning \n Start typing skill, task desc and then click **Run AutoPlanning** to see the output.""")

    default_skill = '创建个知识库问答系统'
    default_desc = '1、选择知识库，对知识库进行问答。'
    default_params = {'openai_api_key': '',
                      'openai_proxy' : '',
                      'serpapi_api_key': '',
                      'collection_name': [''],
                      'database_uri': ['']}
    default_params = json.dumps(default_params, ensure_ascii=False, indent=2)

    with gr.Row():
        skill = gr.Textbox(label='Skill Input', placeholder='skill input', value=default_skill, interactive=True, lines=1)
        task_desc = gr.Textbox(label='TaskDesc Input', placeholder='taskdesc input', value=default_desc, interactive=True, lines=2)
        global_params = gr.Textbox(label='Global param Input', placeholder='param input', value=default_params, interactive=True, lines=3)
        out0 = gr.components.File(label='FlowFile')

    btn0 = gr.Button('Run AutoPlanning')
    btn0.click(fn=run, inputs=[skill, task_desc, global_params], outputs=out0)

    demo.launch(server_name='192.168.106.12', server_port=9119, share=True)

