from .task_definitions import TASK_DESCRIPTIONS, TASK_NAMES

system_template = f"""
Create a Python list of task objects that align with the provided instruction and plan. Task objects must be Python dictionaries, and the output should strictly conform to a Python list of JSON objects.

You must use only the tasks provided in the description:

{TASK_DESCRIPTIONS}

task_name could be only one of the task names below:
{TASK_NAMES}
"""

human_template = """
Create a Python list of task objects that align with the provided instruction and all steps of the plan.

Task objects must be Python dictionaries, and the output should strictly conform to a Python list of JSON objects.

Follow these detailed guidelines:

Task Objects: Create a Python dictionary for each task using the following keys:

step: It represents the step number corresponding to which plan step it matches
task_type: Should match one of the task names provided in task descriptions.
description: Provide a brief description of the task's goal, mirroring the plan step.
master_node: The master node of task_type.

Ensure that each task corresponds to each step in the plan, and that no step in the plan is omitted.
Ensure that an master node of task does not change.

##########################
Instruction:
创建个文件问答系统: 1、上传文件并对文件内容进行问答。
Plan:
1. Use 'FileRetrievalQA' to conduct question and answer on the upload file.
List of Task Objects (Python List of JSON):
[
    {{
        "step": 1,
        "task_type": "FileRetrievalQA",
        "description": "Question and answer based on the content of the upload file.",
        "master_node": "RetrievalQA"
    }}
]
##########################
Instruction:
创建个知识库问答系统: 1、选择知识库并对知识库进行问答。
Plan:
1. Use 'KnowledgeRetrievalQA' to conduct question and answer on the knowledge base.
List of Task Objects (Python List of JSON):
[
    {{
        "step": 1,
        "task_type": "KnowledgeRetrievalQA",
        "description": "Question and answer on the selected knowledge base.",
        "master_node": "RetrievalQA"
    }}
]
##########################
Instruction:
创建个合同审核系统：1、上传合同pdf文件并对合同内容进行问答；2、当涉及到合同数值计算问题时，请调用计算器工具；3、当涉及到需要查外部信息时，请调用搜索引擎工具；
Plan:
1. Use 'FileRetrievalQA' to conduct question and answer on the upload contract file.
2. Use 'Calculator' to compute numerical calculations related to the contract.
3. Use 'SerpAPI' to look up external information what is not included in the contract.
List of Task Objects (Python List of JSON):
[
    {{
        "step": 1,
        "task_type": "FileRetrievalQA",
        "description": "Question and answer on the upload contract file.",
        "master_node": "RetrievalQA"
    }},
    {{
        "step": 2,
        "task_type": "Calculator",
        "description": "Compute numerical calculations related to the contract.",
        "master_node": "Calculator"
    }},
    {{
        "step": 3,
        "task_type": "SerpAPI",
        "description": "Look up external information which is not included in the contract.",
        "master_node": "Search"
    }}
]
##########################
Instruction:
{instruction}
Plan:
{plan}
List of Task Objects (Python List of JSON):
"""
