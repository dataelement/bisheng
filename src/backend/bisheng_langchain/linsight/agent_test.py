import asyncio
import os

from langchain_community.chat_models import ChatTongyi
from pydantic import SecretStr

from bisheng.api.services.linsight.workbench_impl import LinsightWorkbenchImpl
from bisheng.api.services.workstation import WorkStationService
from bisheng.tool.domain.services.executor import ToolExecutor
from bisheng.tool.domain.services.tool import ToolServices
from bisheng_langchain.linsight.agent import LinsightAgent
from bisheng_langchain.linsight.const import TaskMode, ExecConfig
from bisheng_langchain.linsight.event import NeedUserInput, TaskStart, TaskEnd, ExecStep


async def get_linsight_agent():
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
    tools = await ToolExecutor.init_by_tool_ids(config_tool_ids, app_id='linsight_test', app_name='linsight_test',
                                                user_id=0, llm=chat)
    # 获取灵思预置的工具，本地文件处理和知识库检索
    linsight_tools = await ToolServices.init_linsight_tools(root_path=root_path)
    used_tools = linsight_tools + tools

    # 获取本地文件相关工具
    query = "分析该目录下的简历文件（仅限txt格式），挑选出符合要求的简历。要求包括：python代码能力强，有大模型相关项目经验，有热情、主动性高"

    agent = LinsightAgent(llm=chat, query=query, tools=used_tools, file_dir=root_path,
                          task_mode=TaskMode.FUNCTION.value,
                          exec_config=ExecConfig(debug=True, debug_id="test"))
    return agent


async def async_main():
    agent = await get_linsight_agent()

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
    feedback = "需要补充更多关于秦始皇兵马俑的历史背景信息"
    feedback_sop = ""
    async for one in agent.feedback_sop(sop, feedback, []):
        feedback_sop += one.content
    print(f"feedback sop: {feedback_sop}")
    sop = feedback_sop

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
    agent = await get_linsight_agent()

    sop = """标准操作流程（SOP）：  
基于目录简历筛选大模型岗位候选人

---

**1. 问题概述**  
本流程用于在指定目录下，从所有txt格式的简历文件中，自动筛选出满足如下岗位能力要求的候选人：  
- Python代码能力强  
- 有大模型相关项目经验  
- 具备热情、主动性高等软素质  
适用于批量简历文件筛查，输出筛选结果报告。

---

**2. 所需的工具和资源**  
- @list_files：用于列出目录下所有txt文件  
- @read_text_file：用于读取简历内容  
- @search_text_in_file：辅助定位关键词  
- @write_text_file：生成和写入筛选结果  
**最佳实践：**优先批量处理文件，高效检索软硬技能，多维度关键词搜索。

---

**3. 步骤说明**

1. 使用@list_files获取指定目录下所有*.txt简历文件路径。
2. 对于每个txt简历文件：  
   a. 利用@read_text_file整段读取简历内容。  
   b. 分别搜索硬性条件关键词，例如“Python”，“编程”，“大模型”，“LLM”，“NLP”等，判断是否具备技术要求（可通过@search_text_in_file辅助确认）。  
   c. 搜索软性素质相关关键词如“热情”、“主动”、“自我驱动”、“积极”等。  
3. 对所有满足上述三项筛选条件的简历，收集关键信息（如文件名、命中条件摘要）。
4. 结果输出：将筛选通过简历的关键信息，以Markdown格式写入到筛选报告（如筛选结果.md），便于后续查阅。
5. 最终输出“筛选结果.md”文件即为筛查结果报告。

---

**示例输出结构（Markdown）**  
```markdown
# 简历筛选结果

## 满足条件的候选人列表

### 1. 文件名：resume_zhangsan.txt
- 技能：Python、NLP、大模型项目
- 软素质：热情、主动

### 2. 文件名：resume_lisi.txt
- 技能：Python、LLM开发
- 软素质：自我驱动、积极
...
```

---

**注意事项**  
- 关键词匹配可适当使用同义词扩展，以防遗漏。  
- 文件处理应确保不会丢失原始简历。  
- 报告内容简明，利于人工后续甄别。

（本SOP适用于批量文本简历基于技术与素质条件的快速筛查任务）"""
    task_info = [
        {'step_id': 'step_1', 'description': '获取指定目录下所有txt格式的简历文件路径。', 'profile': '文件检索机器人',
         'target': '列出/Users/zhangguoqing/works/bisheng/src/backend/bisheng_langchain/linsight/data下的所有txt格式简历文件路径',
         'sop': '使用@list_files工具，检索所给目录下所有txt文件，返回完整路径列表。',
         'prompt': '请使用@list_files工具列出/Users/zhangguoqing/works/bisheng/src/backend/bisheng_langchain/linsight/data目录下所有txt后缀简历文件的路径。',
         'input': ['query'], 'node_loop': False, 'id': 'c984c953e8fd4c4bbee14d6090cf8718',
         'next_id': ['85e43a1507b94ffabf7195f5559a9209']},
        {'step_id': 'step_2', 'description': '批量读取每个简历文件内容并筛查是否符合岗位要求，收集通过的简历关键信息。',
         'profile': '简历筛查机器人',
         'target': '判断每份简历是否同时符合技术与软素质要求，并汇总关键信息（文件名、命中条件等）',
         'sop': "对step_1返回的所有txt文件，依次读取原文，划分为：\n1. 检查是否包含Python相关技能与代码经验（如‘Python’、‘编程’、‘开发’等关键词）。\n2. 检查是否有大模型、LLM、NLP、Transformer、深度学习等相关项目或经验描述。\n3. 检查内容中是否有'热情'、'主动'、'自我驱动'、'积极'等软素质词语。\n4. 对三个条件全部满足的简历，提取文件名及命中关键词说明，组织成结构化信息。\n（检索与写作合并，避免大量细节传递）",
         'prompt': '你需要读取step_1中每个txt简历，判断：\n- 是否包含Python代码能力、NLP、大模型、LLM等关键词，并描述相关项目经验；\n- 是否具备热情、主动、自我驱动等软素质（可扩展同义表达）；\n对全部符合的简历，记录文件名、技能关键词、软素质关键词。\n返回一个用于报告的结构化信息列表。',
         'input': ['step_1'], 'node_loop': True, 'id': '85e43a1507b94ffabf7195f5559a9209',
         'next_id': ['380b4b7693c14568a45500c4a77f9413']},
        {'step_id': 'step_3', 'description': '将筛查通过的简历结构化信息按Markdown格式输出为筛选结果报告。',
         'profile': '报告生成机器人', 'target': '生成并写入筛查通过简历的报告文件（筛选结果.md）',
         'sop': '根据step_2输出的信息，整理并生成符合指定模板的Markdown格式报告：\n1. 标题：简历筛选结果。\n2. 下设‘满足条件的候选人列表’，每个候选人包含文件名、技能命中、软素质命中。\n3. 调用@write_text_file将该内容写入‘筛选结果.md’。',
         'prompt': '将step_2中收集到的通过简历关键信息，按如下Markdown格式生成报告内容，并写入筛选结果.md：\n# 简历筛选结果\n## 满足条件的候选人列表\n### 1. 文件名：xxx\n- 技能：xxx\n- 软素质：xxx\n...',
         'input': ['step_2'], 'node_loop': False, 'id': '380b4b7693c14568a45500c4a77f9413'}]

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


if __name__ == '__main__':
    asyncio.run(async_main())
    # asyncio.run(only_exec_task())
