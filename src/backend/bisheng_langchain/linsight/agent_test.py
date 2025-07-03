import asyncio
import os

from langchain_community.chat_models import ChatTongyi
from pydantic import SecretStr

from bisheng_langchain.gpts.load_tools import load_tools
from bisheng_langchain.linsight.agent import LinsightAgent
from bisheng_langchain.linsight.event import NeedUserInput


def get_linsight_agent():
    bing_api_key = os.environ.get('bing_api_key')
    qwen_api_key = os.environ.get('qwen_api_key')
    file_dir = "/Users/zhangguoqing/works/bisheng/src/backend/bisheng_langchain/linsight/data"

    used_tools = load_tools({
        "bing_search": {
            "bing_subscription_key": bing_api_key,
            "bing_search_url": "https://api.bing.microsoft.com/v7.0/search",
        },
        "get_current_time": {},
        "list_files": {"root_path": file_dir},
        "get_file_details": {"root_path": file_dir},
        "search_files": {"root_path": file_dir},
        "search_text_in_file": {"root_path": file_dir},
        "read_text_file": {"root_path": file_dir},
        "write_text_file": {"root_path": file_dir},
        "replace_file_lines": {"root_path": file_dir},
    })
    print("used tools:", used_tools)
    chat = ChatTongyi(api_key=SecretStr(qwen_api_key), model="qwen-max-latest", streaming=True,
                      model_kwargs={'incremental_output': True})

    # 获取本地文件相关工具
    query = "分析该目录下的简历文件（仅限txt格式），挑选出符合要求的简历。要求包括：python代码能力强，有大模型相关项目经验，有热情、主动性高"

    agent = LinsightAgent(llm=chat, query=query, tools=used_tools, file_dir=file_dir)
    return agent


async def async_main():
    agent = get_linsight_agent()

    # 生成sop
    sop = ""
    async for one in agent.generate_sop(""):
        sop += one.content
    print(f"first sop: {sop}")

    # # 反馈sop
    # feedback = "需要补充更多关于秦始皇兵马俑的历史背景信息"
    # feedback_sop = ""
    # async for one in agent.feedback_sop(sop, feedback, []):
    #     feedback_sop += one.content
    # print(f"feedback sop: {feedback_sop}")
    # sop=feedback_sop

    task_info = await agent.generate_task(sop)
    print(f"task_info: {task_info}")

    async for event in agent.ainvoke(task_info, sop):
        print(event)

    all_task_info = await agent.get_all_task_info()
    print(all_task_info)


async def only_exec_task():
    agent = get_linsight_agent()

    sop = """
    ### 标准操作流程 (SOP)
#### 问题概述
本SOP旨在分析指定目录下的简历文件（仅限txt格式），筛选出符合以下要求的简历：  
1. Python代码能力强  
2. 有大模型相关项目经验  
3. 热情高、主动性突出  
最终输出为Markdown格式，便于阅读和理解。适用范围为本地目录中存储的简历文件。
---
#### 所需工具和资源
- **工具**:  
  - `list_files`: 列出指定目录下的所有文件。  
  - `search_text_in_file`: 在文本文件中搜索关键词并提取上下文内容。  
  - `write_text_file`: 将结果写入Markdown文件。  
- **资源**:  
  - 包含简历的本地目录路径。  
  - 关键词列表：`python`, `大模型`, `热情`, `主动性`。  
**最佳实践**:  
- 使用`search_text_in_file`时，确保关键词尽可能短且具体，以提高匹配精度。  
- 写入Markdown文件时，分段落组织内容，确保输出清晰易读。
---
#### 步骤说明
1. **列出目录中的所有文件**  
   使用@`list_files`列出目标目录下的所有文件，并过滤出`.txt`格式的简历文件。  
   ```json
   {
     "directory_path": "目标目录路径"
   }
   ```
2. **初始化Markdown文件结构**  
   使用@`write_text_file`创建一个空的Markdown文件，定义标题和基本结构。  
   ```json
   {
     "file_path": "output/resume_analysis.md",
     "content": "# 符合要求的简历分析\n\n## 符合条件的候选人\n\n",
     "start_line": 0
   }
   ```
3. **逐个分析简历文件**  
   遍历步骤1中获取的所有`.txt`文件，对每个文件执行以下操作：  
   - **搜索关键词**  
     使用@`search_text_in_file`在文件中搜索关键词`python`, `大模型`, `热情`, `主动性`。  
     ```json
     {
       "file_path": "当前文件路径",
       "keyword": "python"
     }
     ```  
     对其他关键词重复上述操作，记录匹配结果及其上下文。
   - **评估匹配结果**  
     如果文件中包含所有关键词，则认为该简历符合条件。
4. **将符合条件的简历信息写入Markdown文件**  
   对于符合条件的简历，使用@`write_text_file`将其信息追加到Markdown文件中。  
   ```json
   {
     "file_path": "output/resume_analysis.md",
     "content": "### 候选人: 文件名\n- Python能力: 是\n- 大模型经验: 是\n- 热情与主动性: 是\n\n上下文内容: ...\n\n",
     "start_line": -1
   }
   ```
5. **完成Markdown文件**  
   在Markdown文件末尾添加总结部分，统计符合条件的简历数量。  
   ```json
   {
     "file_path": "output/resume_analysis.md",
     "content": "\n## 总结\n共找到 X 份符合条件的简历。",
     "start_line": -1
   }
   ```
---
#### 输出内容
- 文件名: `resume_analysis.md`  
- 文件内容示例:  
  ```markdown
  # 符合要求的简历分析
  ## 符合条件的候选人
  ### 候选人: resume_001.txt
  - Python能力: 是
  - 大模型经验: 是
  - 热情与主动性: 是
  上下文内容: ...
  ### 候选人: resume_003.txt
  - Python能力: 是
  - 大模型经验: 是
  - 热情与主动性: 是
  上下文内容: ...
  ## 总结
  共找到 2 份符合条件的简历。
  ```"""
    task_info = [
        {'step_id': 'step_1', 'description': '列出目标目录下的所有txt格式简历文件。',
         'profile': '负责列出指定目录下的所有文件，并过滤出符合要求的.txt文件。',
         'target': '获取符合条件的简历文件路径列表。',
         'sop': '使用list_files工具列出目标目录下的所有文件，筛选出扩展名为.txt的文件。',
         'prompt': '请列出目标目录中的所有文件，并返回扩展名为.txt的文件路径列表。', 'input': ['query'],
         'node_loop': False, 'id': '8690968ac8934effa5cb8438e342b02a',
         'next_id': ['52c914546c6844798dbf3474a01396cd']},
        {'step_id': 'step_2', 'description': '初始化Markdown文件结构。',
         'profile': '负责创建一个空的Markdown文件，并定义基本结构。',
         'target': '创建初始Markdown文件以供后续写入分析结果。',
         'sop': '使用write_text_file工具创建并初始化Markdown文件的基本结构。',
         'prompt': '请创建一个名为resume_analysis.md的Markdown文件，并写入标题和基本结构。', 'input': [],
         'node_loop': False, 'id': 'edcf36721fff4db9bdb8374638563c9b'},
        {'step_id': 'step_3', 'description': '逐个分析简历文件，搜索关键词并评估匹配结果。',
         'profile': '负责逐个读取简历文件，搜索关键词并判断是否符合要求。',
         'target': '筛选出符合条件的简历，并记录相关信息。',
         'sop': '遍历步骤1中获取的所有.txt文件，对每个文件使用search_text_in_file工具搜索关键词（python、大模型、热情、主动性），评估匹配结果。',
         'prompt': '请逐个分析简历文件，搜索关键词并判断是否包含所有关键词。如果符合要求，请记录文件名及相关上下文信息。',
         'input': ['step_1'], 'node_loop': True, 'id': '52c914546c6844798dbf3474a01396cd',
         'next_id': ['7794d7646efc4ad69d868273e63304f0']},
        {'step_id': 'step_4', 'description': '将符合条件的简历信息写入Markdown文件。',
         'profile': '负责将符合条件的简历信息追加到Markdown文件中。',
         'target': '在Markdown文件中记录符合条件的简历信息。',
         'sop': '对步骤3中筛选出的每个符合条件的简历，使用write_text_file工具将其信息追加到Markdown文件中。',
         'prompt': '请将符合条件的简历信息追加到resume_analysis.md文件中，包括文件名及匹配的上下文内容。',
         'input': ['step_3'], 'node_loop': True, 'id': '7794d7646efc4ad69d868273e63304f0',
         'next_id': ['55bb8231c82141729b81ab6285092072']},
        {'step_id': 'step_5', 'description': '完成Markdown文件，添加总结部分。',
         'profile': '负责在Markdown文件末尾添加总结部分。',
         'target': '统计符合条件的简历数量，并完成Markdown文件。',
         'sop': '使用write_text_file工具在Markdown文件末尾添加总结部分，统计符合条件的简历数量。',
         'prompt': '请在resume_analysis.md文件末尾添加总结部分，统计符合条件的简历数量。', 'input': ['step_4'],
         'node_loop': False, 'id': '55bb8231c82141729b81ab6285092072'}]
    async for event in agent.ainvoke(task_info, sop):
        print(event)
        if isinstance(event, NeedUserInput):
            print("============ need user input ============")
            user_input = input(f"需要用户输入，原因：{event.call_reason} (任务ID: {event.task_id}): ")
            await agent.continue_task(event.task_id, user_input)
    all_task_info = await agent.get_all_task_info()
    print(all_task_info)


if __name__ == '__main__':
    # asyncio.run(async_main())
    asyncio.run(only_exec_task())
