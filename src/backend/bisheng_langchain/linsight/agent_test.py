import asyncio
import os

from langchain_community.chat_models import ChatTongyi
from pydantic import SecretStr

from bisheng_langchain.gpts.load_tools import load_tools
from bisheng_langchain.linsight.agent import LinsightAgent
from bisheng_langchain.linsight.const import TaskMode
from bisheng_langchain.linsight.event import NeedUserInput, TaskStart, TaskEnd, ExecStep


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

    agent = LinsightAgent(llm=chat, query=query, tools=used_tools, file_dir=file_dir, task_mode=TaskMode.REACT.value)
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

    sop = """### 标准操作流程 (SOP)

#### 问题概述
本SOP旨在指导大模型分析指定目录下的简历文件（仅限txt格式），筛选出符合以下要求的简历：
- Python代码能力强
- 有大模型相关项目经验
- 热情高、主动性高  
输出结果将以Markdown格式呈现，便于阅读和理解。

#### 所需的工具和资源
1. **工具**：
   - @search_files：用于搜索指定目录中的txt文件。
   - @read_text_file：读取简历文件内容。
   - @write_text_file：将筛选结果写入Markdown文件。
2. **最佳实践**：
   - 使用`search_files`时，设置正则表达式匹配`.txt`文件。
   - 每次读取文件内容时，限制行数为50行以提高效率。
   - 输出结果文件命名为`resume_analysis_results.md`。

#### 步骤说明
1. **搜索简历文件**  
   使用@search_files工具，在指定目录中搜索所有`.txt`文件。  
   参数示例：
   ```json
   {
     "directory_path": "./resumes",
     "pattern": "*.txt"
   }
   ```

2. **初始化结果文件**  
   使用@write_text_file工具，创建一个空的Markdown文件`resume_analysis_results.md`，并写入标题和表头。  
   参数示例：
   ```json
   {
     "file_path": "./resume_analysis_results.md",
     "content": "# 符合要求的简历列表\n\n| 文件名 | 符合条件 |\n|--------|----------|\n",
     "start_line": 0
   }
   ```

3. **逐个分析简历文件**  
   对每个找到的简历文件执行以下步骤：
   - 使用@read_text_file工具读取文件内容。  
     参数示例：
     ```json
     {
       "file_path": "./resumes/resume1.txt",
       "start_line": 1,
       "num_lines": 50
     }
     ```
   - 检查文件内容是否包含关键词：“Python”、“大模型”、“热情”、“主动性”。  
     如果全部关键词均存在，则判定该简历符合条件。

4. **记录符合条件的简历**  
   如果简历符合条件，使用@write_text_file工具将文件名和结果追加到`resume_analysis_results.md`中。  
   参数示例：
   ```json
   {
     "file_path": "./resume_analysis_results.md",
     "content": "| resume1.txt | 是 |\n",
     "start_line": -1
   }
   ```

5. **完成分析并总结**  
   当所有文件分析完成后，使用@write_text_file工具在结果文件末尾添加总结信息。  
   参数示例：
   ```json
   {
     "file_path": "./resume_analysis_results.md",
     "content": "\n## 总结\n本次共分析了X份简历，其中Y份符合要求。",
     "start_line": -1
   }
   ```

#### 输出内容
最终输出的文件`resume_analysis_results.md`将包含以下内容：
- 符合要求的简历列表（文件名及是否符合条件）。
- 总结信息，包括总分析数量和符合条件的数量。"""
    task_info = [
        {'step_id': 'step_1', 'description': '搜索指定目录下的所有txt格式简历文件。', 'profile': '文件搜索机器人',
         'target': '找到所有符合条件的txt文件路径。', 'sop': '使用@search_files工具，在指定目录中搜索所有`.txt`文件。',
         'prompt': '在目录`./resumes`中搜索所有`.txt`文件。', 'input': ['query'], 'node_loop': False,
         'id': 'd14b9b85e6034fca99654cc7bed719a6', 'next_id': ['93b9c295918a40958148e4e4df5526be']},
        {'step_id': 'step_2', 'description': '初始化结果文件，创建一个空的Markdown文件并写入标题和表头。',
         'profile': '文件初始化机器人', 'target': '创建并初始化`resume_analysis_results.md`文件。',
         'sop': '使用@write_text_file工具，创建一个空的Markdown文件`resume_analysis_results.md`，并写入标题和表头。',
         'prompt': '创建文件`resume_analysis_results.md`并写入标题和表头：`# 符合要求的简历列表\n\n| 文件名 | 符合条件 |\n|--------|----------|\n`。',
         'input': ['query'], 'node_loop': False, 'id': '172221cd302d42b9a7dbb99273045ab1'},
        {'step_id': 'step_3', 'description': '逐个分析简历文件内容，检查是否符合筛选条件。', 'profile': '简历分析机器人',
         'target': '分析每个简历文件内容，判断是否包含关键词：Python、大模型、热情、主动性。',
         'sop': '对每个简历文件，使用@read_text_file工具读取文件内容，并检查是否包含关键词。',
         'prompt': '对于每个简历文件，读取前50行内容并检查是否包含以下关键词：Python、大模型、热情、主动性。如果全部关键词均存在，则判定该简历符合条件。',
         'input': ['step_1'], 'node_loop': True, 'id': '93b9c295918a40958148e4e4df5526be',
         'next_id': ['75ac818d7ee14eff882058831b63c892', '7314747c11534165b302fb379ea6fd4e']},
        {'step_id': 'step_4', 'description': '记录符合条件的简历到结果文件中。', 'profile': '结果记录机器人',
         'target': '将符合条件的简历信息追加到`resume_analysis_results.md`文件中。',
         'sop': '使用@write_text_file工具，将符合条件的简历文件名和结果追加到`resume_analysis_results.md`中。',
         'prompt': '如果简历符合条件，将其文件名和结果追加到`resume_analysis_results.md`中，格式为：`| 文件名 | 是 |\n`。',
         'input': ['step_3'], 'node_loop': True, 'id': '7314747c11534165b302fb379ea6fd4e',
         'next_id': ['75ac818d7ee14eff882058831b63c892']},
        {'step_id': 'step_5', 'description': '完成分析并总结，添加总结信息到结果文件。', 'profile': '总结机器人',
         'target': '在结果文件末尾添加总结信息，包括总分析数量和符合条件的数量。',
         'sop': '使用@write_text_file工具，在结果文件末尾添加总结信息。',
         'prompt': '在`resume_analysis_results.md`文件末尾添加总结信息：`## 总结\n本次共分析了X份简历，其中Y份符合要求。`。',
         'input': ['step_3', 'step_4'], 'node_loop': False, 'id': '75ac818d7ee14eff882058831b63c892'}]
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
    # asyncio.run(async_main())
    asyncio.run(only_exec_task())
