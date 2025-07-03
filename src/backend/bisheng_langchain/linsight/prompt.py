# 生成sop的prompt模板, variables -> query: 用户问题；sop：参考sop; tools_str: 已有工具字符串
SopPrompt = """基于以下信息创建一个标准操作流程(SOP):
请基于用户需求的生成SOP：
1. SOP指的是通过哪些标准步骤能指导大模型解决用户的问题。
需要包含一下内容：
2. 问题概述 - 简要描述问题和目标，需要体现本SOP的适用范围
3. 所需的工具和资源 - 列出解决此类问题所需的工具、库或资源（需要是已有可获取的）,以及使用工具的最佳实践。
4. 步骤说明 - 提供清晰的步骤指导
5. 生成的SOP里需要独立完成问题，不能包含询问用户的步骤。
6. 输出的内容需要简练。
7. 如果用户意图需要输出很长的内容，推荐使用写文档的工具，写文档的工具需要先拆解需要写的目录结构，然后给定一个文件名，然后一步一步的完成，每一步都写入同一个文件。
8. 使用@来说明使用什么工具。

已有工具：
{tools_str}

模仿以下SOP的格式：
{sop}

用户需求: 
{query}

输出应当是Markdown格式，便于阅读和理解。请确保SOP是实用的，可以帮助用户解决类似问题。
输出内容应该简练，只输出SOP，不要输出其他内容"""

# 调整sop时的反馈prompt模板, variables -> query: 用户问题；sop：参考sop；feedback：用户反馈; history_summary: 历史执行过程
# variables -> tools_str: 已有工具字符串
FeedBackSopPrompt = """基于以下信息创建一个标准操作流程(SOP):

已有工具：
{tools_str}

用户需求: {query}

解决问题的执行过程:
{history_summary}

{sop}

用户对以上执行过程，SOP和结果的反馈：
{feedback}

请基于以上内容和反馈创建一个清晰、结构化，且更好满足用户需求的SOP文档，包括：
1. 问题概述 - 简要描述问题和目标，需要体现本SOP的适用范围
2. 所需的工具和资源 - 列出解决此类问题所需的工具、库或资源（需要是已有可获取的）
3. 详细的步骤说明 - 提供清晰的步骤指导
4. 可能遇到的问题和解决方案 - 列出常见问题及其解决方法

输出应当是Markdown格式，便于阅读和理解。请确保SOP是实用的，可以帮助用户解决类似问题。
输出内容应该简练"""

# 生成一级子任务的prompt模板, variables -> current_time: 当前时间；file_dir: 用户上传的文件路径；sop: 用户SOP；query: 用户问题
GenerateTaskPrompt = """你是一个任务规划专家，请根据用户的需求和SOP，规划出完成任务需要多少个具体的机器人，每个机器人需要完成哪些任务，以及这些机器人之间是如何协同工作的。
要求：
1. 根据用户的需求和SOP，规划出粗粒度的步骤。
2. 具体哪些机器人来完成这些步骤。以及他们之间的协同工作方式。协同方式有（串行）。
3. 为每个机器人确定他们profile，target，sop,prompt,node-loop(机器人内部是否需要循环)。
4. 尽量避免步骤之间传递大量细节信息，例如如果存在分章节检索并写作的步骤，需要将检索和写作合并到一步中，以此避免步骤之间传递大量细节信息。
5. 如果用户需求特别简单，例如只需要执行一个步骤，请直接返回这个步骤的Json。
6. 通过以下Json格式返回结果：
```json
{{
    "steps": [
        {{
            "step_id": "step_1",
            "description": "step_1的描述",
            "profile": "step_1的profile",
            "target": "step_1的target",
            "sop": "step_1的sop",
            "prompt": "step_1的prompt",
            "input": [""]
            "node_loop": True/False
        }}
        ,....
    ]
}}
```
字段解释：
"input": 这一步的输入，必须是前置步骤的step_id或"query",可以多个。"query"代表用户的原始问题。
"node_loop": step_1是否需要循环，通常在相似需求需要重复执行的时候需要循环."
"prompt": 这一步的prompt，通常是这一步的输入和上一步的输出，需要包含执行这一步所需的全部输入信息。

以下是一些标准信息：
当前时间：{current_time}
当前路径：{file_dir}

用户SOP：
{sop}

用户问题：
{query}
"""

# 单个agent的prompt模板
# variables -> profile:agent角色; current_time: 当前时间；file_dir: 用户上传的文件路径；sop: 用户SOP；query: 用户最终问题；
# workflow: 任务整体规划；processed_steps: 已经处理的步骤；input_str: 用户输入信息；step_id: 当前任务id
# target: 当前任务目标；single_sop: 当前任务遵循的SOP
SingleAgentPrompt = """你是一个强大的{profile}，可以使用提供的工具来回答用户问题并执行任务。
在最后的回答中，需要包含接下来需要执行步骤所需的所有信息，例如本次任务的结论，文件保存的路径等等

以下是一些标准信息：
当前时间：{current_time}
当前路径：{file_dir}

用户最终问题: 
"{query}"

用户提供的完整SOP: 
{sop}

这是任务整体规划：
{workflow}

{processed_steps}

{input_str}

当前任务为：{step_id}，步骤目标为：
{target}
当你完成了阶段目标，应该结束执行。

当前应该遵守的SOP：
{single_sop}

请根据阶段目标，使用适当的工具来完成任务。"""

# 并发agent拆分子任务的prompt模板
# variables -> query: 用户问题；sop: 用户SOP；workflow: 任务整体规划；
# processed_steps: 已经处理的步骤；input_str: 用户输入信息; prompt: 当前阶段问题
LoopAgentSplitPrompt = """你是一名专业的流程拆解专家，请根据用户提供的任务要求，将复杂内容拆分为清晰、完整且互不重复的并行操作任务。请按以下规则执行：
你需要先分析再拆解，分析用户的问题，并根据问题进行拆解。
你的拆解将会逐个送入接下来的流程节点中进行处理。
接下来的流程节点会根据你的拆解结果，逐个进行并行处理，因此，接下来的流程节点的所有上下文是独立的，需要你确保拆解结果的独立性。
首先你要输出每个任务都共享的内容：
1. 总体任务目标。
2. 总体方法。
3. 已经完成的内容。
针对每个任务，你需要输出以下内容：
1. 当前目标。
2. 当前方法。当前方法要参考总体方法，例如使用工具的情况不能遗漏。


请用以下格式模板响应：
```json
{{
  "总体任务目标": "<总体任务目标>",
  "总体方法": "<总体方法>",
  "已经完成的内容": "<已经完成的内容>",
  "任务列表": [
    {{
      "当前目标": "<当前目标>",
      "当前方法": "<当前方法>"
    }},
    {{
        "当前目标": "<当前目标>",
        "当前方法": "<当前方法>"
    }},
    ...
  ]
}}
```

用户最终问题: 
{query}

用户提供的完整SOP: 
{sop}

这是任务整体规划：
{workflow}

你现在已经完成了{processed_steps}

{input_str}

阶段问题：
{prompt}"""

# 并发执行子任务的agent的prompt模板
# variables -> profile: agent的角色；current_time: 当前时间；file_dir: 用户上传的文件路径；
# original_query: 总体任务目标；original_method: 总体方法；original_done: 已经完成的内容；last_answer: 上步骤的答案
# single_sop: 当前任务遵循的SOP；step_id: 当前任务id; target: 当前任务目标；
LoopAgentPrompt = """你是一个强大的{profile}，可以使用提供的工具来回答用户问题并执行任务。
在最后的回答中，需要包含接下来需要执行步骤所需的所有信息，例如本次任务的结论，文件保存的路径等等

以下是一些标准信息：
当前时间：{current_time}
当前路径：{file_dir}

整体任务目标：
{original_query}

整体方法：
{original_method}

已经完成的内容：
{original_done}
{last_answer}

当前方法：
{single_sop}

当前任务为：{step_id}，步骤目标为：
{target}

请根据用户问题，使用适当的工具来完成任务。当你完成了当前用户问题，应该总结回答，并结束执行。"""

# 历史记录总结的prompt模板, 在历史记录过长时使用
# variables -> sop: 标准执行步骤；query: 用户问题；history_str: 历史记录字符串
SummarizeHistoryPrompt = """请总结以下对话历史记录，并基于已有信息尝试回答用户问题:
要求：
1. 已完成步骤的关键结果和产出(尤其是后续步骤会用到的内容)
2. 当前执行进度和所处阶段
3. 下一步的计划和目标。（如果已完成了当前步骤目标，下一步应该是任务结束）
4. 工具执行总结：具体工具调用的执行信息（检索到的资料）会被删除，所以需要整理已有内容，保留后续步骤所必需的细节信息。
5. 在最后输出你的阶段性回答。

请用精炼的语言描述，确保包含所有重要信息。

标准执行步骤:
{sop}

用户问题:
{query}

历史记录:
{history_str}

总结要点："""
