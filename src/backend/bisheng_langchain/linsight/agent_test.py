import asyncio
import os

from langchain_community.chat_models import ChatTongyi
from pydantic import SecretStr

from bisheng_langchain.gpts.load_tools import load_tools
from bisheng_langchain.linsight.agent import LinsightAgent
from bisheng_langchain.linsight.const import TaskMode, ExecConfig
from bisheng_langchain.linsight.event import NeedUserInput, TaskStart, TaskEnd, ExecStep


async def get_linsight_agent_depend_bisheng():
    from bisheng.api.services.assistant_agent import AssistantAgent
    from bisheng.api.services.linsight.workbench_impl import LinsightWorkbenchImpl
    from bisheng.api.services.tool import ToolServices
    from bisheng.api.services.workstation import WorkStationService
    azure_api_key = os.environ.get('azure_api_key')
    qwen_api_key = os.environ.get('qwen_api_key')
    root_path = "/Users/zhangguoqing/works/bisheng/src/backend/bisheng_langchain/linsight/data"

    chat = ChatTongyi(api_key=SecretStr(qwen_api_key), model="qwen-max-latest", streaming=True,
                      model_kwargs={'incremental_output': True})

    # chat = AzureChatOpenAI(azure_endpoint="https://ai-aoai05215744ai338141519445.cognitiveservices.azure.com/",
    #                        api_key=azure_api_key,
    #                        api_version="2024-12-01-preview",
    #                        azure_deployment="gpt-4.1",
    #                        max_retries=3,
    #                        temperature=0,
    #                        max_tokens=1000)

    # 获取工作台配置的工具
    ws_config = await WorkStationService.aget_config()
    config_tool_ids = LinsightWorkbenchImpl._extract_tool_ids(ws_config.linsightConfig.tools or [])
    tools = await AssistantAgent.init_tools_by_tool_ids(config_tool_ids, llm=chat)
    # 获取灵思预置的工具，本地文件处理和知识库检索
    linsight_tools = await ToolServices.init_linsight_tools(root_path=root_path)
    used_tools = linsight_tools + tools

    # 获取本地文件相关工具
    query = "分析该目录下的简历文件，挑选出符合要求的简历。要求包括：python代码能力强，有大模型相关项目经验，有热情、主动性高"

    agent = LinsightAgent(llm=chat, query=query, tools=used_tools, file_dir=root_path,
                          task_mode=TaskMode.REACT.value,
                          exec_config=ExecConfig(debug=True, debug_id="test"))
    return agent


async def get_linsight_agent_depend_local():
    azure_api_key = os.environ.get('azure_api_key')
    qwen_api_key = os.environ.get('qwen_api_key')
    cloudsway_api_key = os.environ.get('cloudsway_api_key')
    cloudsway_endpoint = os.environ.get('cloudsway_endpoint')
    root_path = "/Users/zhangguoqing/works/bisheng/src/backend/bisheng_langchain/linsight/data"

    chat = ChatTongyi(api_key=SecretStr(qwen_api_key), model="qwen-max-latest", streaming=True,
                      model_kwargs={'incremental_output': True})

    used_tools = load_tools({
        "web_search": {
            "type": "cloudsway",  # 使用那个搜索引擎，config字段里配置对应搜索引擎的配置
            "config": {
                "bing": {"api_key": "xxx",
                         "base_url": "https://api.bing.microsoft.com/v7.0/search"},
                "bocha": {"api_key": "xxx"},
                "jina": {"api_key": ""},
                "serp": {"api_key": "1", "engine": "baidu"},
                "tavily": {"api_key": "1"},
                "cloudsway": {"api_key": cloudsway_api_key, "endpoint": cloudsway_endpoint},
                "searXNG": {"server_url": "http://192.168.106.116:8889"}},
        },
        "get_current_time": {},
        "list_files": {"root_path": root_path},
        "get_file_details": {"root_path": root_path},
        "search_files": {"root_path": root_path},
        "search_text_in_file": {"root_path": root_path},
        "read_text_file": {"root_path": root_path},
        "add_text_to_file": {"root_path": root_path},
        "replace_file_lines": {"root_path": root_path},
    })
    query = "分析该目录下的简历文件(md或txt)，挑选出符合要求的简历。要求包括：python代码能力强，有大模型相关项目经验，有热情、主动性高"
    agent = LinsightAgent(llm=chat, query=query, tools=used_tools, file_dir=root_path,
                          task_mode=TaskMode.REACT.value,
                          exec_config=ExecConfig(debug=True, debug_id="test"))
    return agent


async def async_main():
    # agent = await get_linsight_agent_depend_bisheng()
    agent = await get_linsight_agent_depend_local()

    sop_template = ""
    # # 检索sop
    # sop_documents, error_msg = await SOPManageService.search_sop("基于目录简历筛选大模型岗位候选人", 3)
    # if not sop_documents:
    #     print("没有找到相关的SOP模板")
    #     return
    # print(f"找到 {len(sop_documents)} 个相关SOP模板")
    # print(f"sop_documents: {sop_documents}")
    # sop_template = "\n\n".join([
    #     f"例子:\n\n{sop.page_content}"
    #     for sop in sop_documents if sop.page_content
    # ])

    sop = ""
    async for one in agent.generate_sop(sop_template):
        sop += one.content
    print(f"first sop: {sop}")

    # 反馈sop
    # feedback = "需要补充更多关于秦始皇兵马俑的历史背景信息"
    # feedback_sop = ""
    # async for one in agent.feedback_sop(sop, feedback, []):
    #     feedback_sop += one.content
    # print(f"feedback sop: {feedback_sop}")
    # sop = feedback_sop

    task_info = await agent.generate_task(sop)
    print(f"task_info: {task_info}")

    async for event in agent.ainvoke(task_info, sop):
        if isinstance(event, NeedUserInput):
            print("============ need user input ============")
            user_input = input(f"需要用户输入，原因：{event.call_reason} (任务ID: {event.task_id}): ")
            await agent.continue_task(event.task_id, user_input)
        elif isinstance(event, TaskStart):
            print(f"============ task start ============ {event}")
        elif isinstance(event, TaskEnd):
            print(f"============ task end ============ {event}")
        elif isinstance(event, ExecStep):
            print(f"============ exec step ============ {event}")

    all_task_info = await agent.get_all_task_info()
    print(all_task_info)


async def only_exec_task():
    agent = await get_linsight_agent_depend_local()
    # agent = await get_linsight_agent_depend_bisheng()

    sop = """# 指导手册：简历筛选与分析

## 概述
### 背景和适用场景
本指导手册适用于从指定目录下的简历文件（md或txt格式）中筛选出符合特定要求的简历。筛选条件包括：Python代码能力强、有大模型相关项目经验、有热情和主动性高。

### 目标
通过自动化流程，快速筛选出符合条件的简历，并将结果以Markdown格式输出，便于用户查看和进一步处理。

---

## 所需工具和资源
- **工具**：
  - @search_files@：搜索目录下的md或txt文件。
  - @read_text_file@：读取文件内容。
  - @search_text_in_file@：在文件中搜索关键词。
  - @add_text_to_file@：将筛选结果写入输出文件。
- **文件**：
  - 用户提供的简历文件存储路径：@简历文件储存信息：{'文件储存在语义检索库中的id':'{id}','文件储存地址':'{文件路径}'}@
- **知识库**：无。

---

## 步骤说明

### 步骤概述
#### 本步骤目标
筛选出符合要求的简历文件，并将结果记录到输出文件中。

#### 本步骤交付结果
- 符合条件的简历文件名及其路径。
- 输出文件：筛选结果的Markdown文件。

#### 依赖前序步骤
无。

#### 拆解为多个互不影响的子步骤执行
1. 搜索目录下的md或txt文件。
2. 逐个读取文件内容并分析是否符合筛选条件。
3. 将符合条件的文件信息写入输出文件。

---

### 步骤详情

#### （1）搜索目录下的md或txt文件
- **目标**：找到目录下的所有md或txt文件。
- **操作**：
  ```python
  result = search_files(directory_path="简历文件储存信息['文件储存地址']", pattern=".*\.(md|txt)$", max_depth=5)
  ```
- **交付结果**：符合条件的文件列表。

#### （2）逐个读取文件内容并分析是否符合筛选条件
- **目标**：判断文件内容是否符合筛选条件。
- **操作**：
  1. 使用`read_text_file`工具读取文件内容：
     ```python
     file_content = read_text_file(file_path="文件路径", start_line=1, num_lines=250)
     ```
  2. 使用`search_text_in_file`工具搜索关键词：
     ```python
     python_result = search_text_in_file(file_path="文件路径", keyword="Python")
     model_result = search_text_in_file(file_path="文件路径", keyword="大模型")
     passion_result = search_text_in_file(file_path="文件路径", keyword="热情")
     ```
  3. 判断是否同时满足三个条件：
     ```python
     if python_result["match_count"] > 0 and model_result["match_count"] > 0 and passion_result["match_count"] > 0:
         # 符合条件
     ```

#### （3）将符合条件的文件信息写入输出文件
- **目标**：将筛选结果写入Markdown文件。
- **操作**：
  ```python
  add_text_to_file(file_path="筛选结果.md", content=f"- {文件名}\n")
  ```

---

### 注意事项
- 文件数量较多时，建议分批处理以提高效率。
- 关键词匹配可能存在误判，需根据实际情况调整关键词。
- 输出文件需清晰标注筛选条件和结果。

---

## 总结
通过本指导手册，用户可以快速筛选出符合特定要求的简历文件，并将结果以Markdown格式输出。整个流程自动化程度高，易于扩展和修改，适用于类似的文件筛选任务。"""
    task_info = [{
        'thought': '第一步是搜索目录下的md或txt文件，这是后续分析的基础。此步骤使用search_files工具，参数包括目录路径和正则表达式模式。无需前置步骤输入。',
        'step_id': 'step_1', 'profile': '搜索简历文件', 'target': '找到目录下的所有md或txt文件',
        'workflow': "使用search_files工具，参数为directory_path='/Users/zhangguoqing/works/bisheng/src/backend/bisheng_langchain/linsight/data'，pattern='.*\\.(md|txt)$'，max_depth=5。",
        'precautions': '确保目录路径正确，避免遗漏文件。', 'input': ['query'], 'node_loop': False,
        'id': '22103c72a2094919885c20b38228bcbe', 'next_id': ['ef7093d77f96403dab83dcceb51b41a6'],
        'display_target': '找到目录下的所有md或txt文件',
        'sop': "使用search_files工具，参数为directory_path='/Users/zhangguoqing/works/bisheng/src/backend/bisheng_langchain/linsight/data'，pattern='.*\\.(md|txt)$'，max_depth=5。"},
        {
            'thought': '第二步是逐个读取文件内容并分析是否符合筛选条件。此步骤需要从step_1获取文件列表，然后使用read_text_file和search_text_in_file工具进行关键词匹配。每个文件需独立处理。',
            'step_id': 'step_2', 'profile': '分析文件内容', 'target': '判断文件内容是否符合筛选条件',
            'workflow': "1. 遍历step_1返回的文件列表；2. 使用read_text_file读取文件内容；3. 使用search_text_in_file分别搜索关键词'Python'、'大模型'、'热情'；4. 判断是否同时满足三个条件。",
            'precautions': '注意文件数量较多时分批处理，避免内存占用过高；关键词匹配可能存在误判，需根据实际情况调整。',
            'input': ['step_1'], 'node_loop': True, 'id': 'ef7093d77f96403dab83dcceb51b41a6',
            'next_id': ['26ca8c05841244f19c66f6412569ee05'], 'display_target': '判断文件内容是否符合筛选条件',
            'sop': "1. 遍历step_1返回的文件列表；2. 使用read_text_file读取文件内容；3. 使用search_text_in_file分别搜索关键词'Python'、'大模型'、'热情'；4. 判断是否同时满足三个条件。"},
        {
            'thought': '第三步是将符合条件的文件信息写入输出文件。此步骤需要从step_2获取符合条件的文件名及其路径，并使用add_text_to_file工具将结果追加到Markdown文件中。',
            'step_id': 'step_3', 'profile': '记录筛选结果', 'target': '将符合条件的文件信息写入Markdown文件',
            'workflow': "1. 遍历step_2返回的符合条件文件列表；2. 使用add_text_to_file工具，参数为file_path='筛选结果.md'，content='- {文件名}\\n'。",
            'precautions': '确保输出文件清晰标注筛选条件和结果，避免重复写入。', 'input': ['step_2'],
            'node_loop': False, 'id': '26ca8c05841244f19c66f6412569ee05',
            'display_target': '将符合条件的文件信息写入Markdown文件',
            'sop': "1. 遍历step_2返回的符合条件文件列表；2. 使用add_text_to_file工具，参数为file_path='筛选结果.md'，content='- {文件名}\\n'。"}]

    example_sop = ""
    agent.sop = sop
    agent.tasks = task_info
    async for event in agent.ainvoke_to_end(sop=example_sop):
        if isinstance(event, NeedUserInput):
            print("============ need user input ============")
            user_input = input(f"需要用户输入，原因：{event.call_reason} (任务ID: {event.task_id}): ")
            await agent.continue_task(event.task_id, user_input)
        elif isinstance(event, TaskStart):
            print(f"============ task start ============ {event}")
        elif isinstance(event, TaskEnd):
            print(f"============ task end ============ {event}")
        elif isinstance(event, ExecStep):
            print(f"============ exec step ============ {event}")
    while True:
        user_input = input("输入exit退出：")
        if user_input == "exit":
            break
        else:
            await dispatch_user_input(agent, user_input)


async def dispatch_user_input(agent, user_input):
    if user_input.startswith("test_copy"):
        new_agent = await agent.copy_agent()
        print(new_agent)
    elif user_input.startswith("test_new_agent"):
        prompt = input("请输入prompt：")
        response = input("请输入response：")
        new_agent = await agent.copy_agent()
        async for event in new_agent.ainvoke_by_prompt(prompt, response):
            if isinstance(event, NeedUserInput):
                print("============ need user input ============")
                user_input = input(f"需要用户输入，原因：{event.call_reason} (任务ID: {event.task_id}): ")
                await agent.continue_task(event.task_id, user_input)
            elif isinstance(event, TaskStart):
                print(f"============ task start ============ {event}")
            elif isinstance(event, TaskEnd):
                print(f"============ task end ============ {event}")
            elif isinstance(event, ExecStep):
                print(f"============ exec step ============ {event}")


if __name__ == '__main__':
    # asyncio.run(async_main())
    asyncio.run(only_exec_task())
