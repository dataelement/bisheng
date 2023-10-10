import os
import json
from flask import Flask, request, Response, abort
from autoplanning_agent import AutoPlanning

app = Flask(__name__)

openai_api_key = os.environ.get('OPENAI_API_KEY', '')
openai_proxy = os.environ.get('OPENAI_PROXY', '')
planning_agent = AutoPlanning(model_name="gpt-4-0613",
                              openai_api_key=openai_api_key)


@app.route("/auto_planning_v1", methods=['POST'])
def auto_planning_v1():
    data = request.json
    skill = data['skill']
    task_desc = data['task_desc']
    global_params = data['global_params']
    global_params = json.loads(global_params)
    try:
        agent_graph = planning_agent(skill=skill, description=task_desc,
            global_params=global_params, input_required_params=False)
        result = {'code': '200', 'msg': '响应成功', 'data': agent_graph}
    except Exception as e:
        print(e)
        result = {'code': '500', 'msg': str(e), 'data': {}}
    return Response(str(result), mimetype='application/json')


def generate_langchain_app():
    # skill = "创建个知识库问答系统"
    # task_desc = "1、选择知识库，对知识库进行问答。"

    # skill = "创建个文件问答系统"
    # task_desc = "1、上传PDF文件，并对文件内容进行问答。"

    # skill = "创建个大模型对话系统"
    # task_desc = "1、跟大模型进行对话。"

    # skill = "创建个csv文件分析系统"
    # task_desc = "1、对csv文件进行问答"

    # skill = "创建个合同审核系统"
    # task_desc = "1、上传合同pdf文件并对合同内容进行查询问答；2、当涉及到合同数值计算问题时，请调用计算器工具；3、当涉及到需要查外部信息时，请调用搜索引擎工具；"

    skill = "创建个财报分析系统"
    task_desc = "1、上传财报pdf文件并对财报内容进行问答；2、当涉及到数值计算问题时，请调用计算器工具；3、当涉及到保荐机构信息时，可以查询保荐机构csv相关文件；4、当涉及到查询股票信息时，请查询对应的sql文件"

    save_file = skill + '.json'
    agent_graph = planning_agent(skill=skill, description=task_desc, save_file=save_file, input_required_params=False)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9118, threaded=True)
    # generate_langchain_app()

