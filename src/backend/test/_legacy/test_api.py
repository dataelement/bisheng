import json
import os
from typing import Optional

import requests


def _test_python_code():
    from bisheng import load_flow_from_json

    TWEAKS = {
        'PyPDFLoader-RJlDA': {},
        'InputFileNode-hikjJ': {
            'file_path':
            'https://bisheng.dataelem.com/bisheng/1673?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin%2F20231025%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20231025T093224Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=b124b651adcfb0aa3c86d821072fa81d3f8e7b42a39ec517f1d146353ef6867b'  # noqa
        },
        'InputNode-keWk3': {},
        'Milvus-VzZtx': {},
        'RetrievalQA-Y4e1R': {},
        'CombineDocsChain-qrRE4': {},
        'RecursiveCharacterTextSplitter-C6YSc': {},
        'ProxyChatLLM-oWqpn': {
            'elemai_api_key':
            'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiaXNoZW5nX29wZW42IiwiZXhwIjoxNzEzNzU0MjUyfQ.ww1l-GTBYJiHV3-U1JcacvWOqYPd-QMpuJIeuO9_OM8'  # noqa
        },
        'HostEmbeddings-EJq6w': {}
    }
    flow = load_flow_from_json('/Users/huangly/Downloads/⭐️ PDF文档摘要-zxf.json', tweaks=TWEAKS)
    # Now you can use it like any chain
    inputs = {'query': '合同甲方是谁', 'id': 'RetrievalQA-Y4e1R'}
    print(flow(inputs))


def _test_uns():

    import base64
    import requests

    # 使用场景1： 文件到tokens
    url = 'http://192.168.106.12:10001/v1/etl4llm/predict'

    filename = '/Users/huangly/Downloads/合同(1).pdf'
    b64_data = base64.b64encode(open(filename, 'rb').read()).decode()
    filename_type = '合同(1).pdf'

    inp = dict(filename=filename_type,
               b64_data=[b64_data],
               mode='partition',
               parameters={
                   'start': 0,
                   'n': None
               })

    resp = requests.post(url, json=inp).json()
    print(resp)


# API URL for the flow
# 定义流程的 API URL
BASE_API_URL = 'https://bisheng.dataelem.com/api/v1/process'


def batch_api(FLOW_ID='30231781-2f58-4cea-bcfc-c20ec65c58b8'):
    questions = {
        'questions': [
            '安装pageoffice时页面报错，提示“写入注册表键时出错”，如何处理？', '操作现金回收，系统提示“银行流水未完成指认”，怎么办？',
            '处置方案变更中--拟处置资产和成本金额为0，如何修改？', '处置方案中“处置效果与收益测算”模块的“处置参考价格”、“预计处置净收益”字段是什么含义，是如何取值的？',
            '处置尽调环节，将多笔债权的合同导入系统后，页面应该展示每笔合同对应的金额，但目前页面展示的是债权总额，为什么会这样？', '传统收购尽调的折现公式是什么？',
            '传统收购尽调录入完成后还需要在系统进行哪些操作？', '对一笔临时的回款做回收资金操作，还款计划变更和资金回收确认应该先做哪个？',
            '方案内容有错误需要修改，但此时方案已经提交到总部，如何操作？', '方案审批的时候，只能下载，不能预览', '合作备忘录出资比例应该如何填写？',
            '合作立项审批协办机构为什么看不见审批流程？', '老系统的单据在新系统如何打印？', '批复逾期，项目需要重新发起方案，应该如何操作？', '如何参加股权决策小组成员？',
            '如何查询债权资产的当前管理责人？', '如何申请结项项目的查询权限？', '如何通过债务人的名称查询项目信息？', '如何增加系统权限？', '是否可以更改项目名称？',
            '收购成本变更对后续流程有什么影响？', '提前还本的线上操作流程', '提前还款如何操作？', '为什么不能下载附件？', '为什么没有可用的电子印章？',
            '无法新增还款计划变更，怎么处理？', '误操作提交了合作备忘录，如何补救？', '项目立项时，项目类型字段选项是空的，应该怎么处理？',
            '项目立项已经审批完成，如何修改项目名称？', '一笔资金流水如何才能关联多个项目？', 'SPV的优先、中间、劣后分层资产信息怎么录入？',
            '处置简版审批方案是否还需要处长审批？', '当天的银行流水什么时候才能在核心系统查询到？', '导入excel报错，如何解决？', '合作备忘录的审批流程是怎么样的？',
            '江苏分公司在进行处置方案审批表决时，如果已经有李明、张楠、方可、刘宇、芦苇进行了投票，而吴天文没有投票，请问可以进入下一步流程吗？',
            '客户是国企并且属于能源类企业，请问在立项时归口管理部门应该选择哪个部门？', '客户为房地产行业的国企，请问在做“其他投放类”的立项时，归口管理部门应该选择哪个部门？',
            '立项审批已完成，此时发现数据有误，是否可以在尽调的时候对立项数据进行修改？', '两个分公司合作的项目，应该由谁来上传方案的回复意见？',
            '其他投放类收购尽调，要确认法院涉诉黑名单，应该在哪里操作？', '如何申请新核心系统的权限？', '使用核心系统对电脑的浏览器有什么要求？',
            '提前还款时，资金的入账顺序是先入本金还是先入利息？', '未处置孳息数据的核算口径', '项目立项审批阶段，是否可以选择其他处室的负责人来审批？',
            '需要修改合作备忘录中的出资规模比例，应该使用哪个功能？', '已经提交尽调审批，如何修改信息？',
            '浙江分公司与江苏分公司合作的项目，由浙江分公司发起立项，请问需要到江苏分公司进行备案吗？', '资金申领审批之前是否必须对收款方做反洗钱排查？'
        ]
    }

    # You can tweak the flow by adding a tweaks dictionary
    # 通过添加一个 tweaks 字典来调整流程
    # 例如：{"OpenAI-XXXXX": {"model_name": "gpt-4"}}

    def run_flow(inputs: dict, flow_id: str, session_id: Optional[str] = None) -> dict:
        """
        Run a flow with a given message and optional tweaks.
        运行流程，使用给定的消息和可选的调整参数。
        :param message: 要发送到流程的消息
        :param flow_id: 要运行的流程的ID
        :param tweaks: 可选的调整参数，用于自定义流程
        :return: 流程的 JSON 响应
        """
        api_url = f'{BASE_API_URL}/{flow_id}'
        payload = {'inputs': inputs, 'session_id': session_id}
        response = requests.post(api_url, json=payload, timeout=30)
        print(f'response {response.status_code}')
        return response.json()

    # Iterate over each question
    # 遍历每个问题
    session_id = None
    for ques in questions['questions']:
        inputs = {'query': ques, 'id': 'SequentialChain-xgOSC'}
        # Run the flow with the question as input
        # 使用问题作为输入运行流程
        res = run_flow(inputs, flow_id=FLOW_ID, session_id=session_id)
        session_id = res['data']['session_id']

        # Add the question to the response
        # 将问题添加到响应中
        res['question'] = ques
        # Create the directory if it doesn't exist
        # 如果目录不存在则创建目录
        os.makedirs('./GPT4', exist_ok=True)
        # Save the response as a JSON file
        # 将响应保存为 JSON 文件
        with open(f'./GPT4/GPT4_res_{ques}.json', 'w') as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        # Print the result
        # 打印结果
        print(f'Response {ques}')


# _test_python_code()
# _test_uns()
# test_input()
batch_api()
