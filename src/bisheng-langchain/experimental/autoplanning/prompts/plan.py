from .task_definitions import TASK_DESCRIPTIONS, TASK_NAMES

system_template = f"""
Create a plan to fulfill the given instruction.
The plan should be broken down into steps. Don't generate impossible steps in the plan because only those tasks are available:
{TASK_DESCRIPTIONS}

Only those task types are allowed to be used:
{TASK_NAMES}
"""

human_template = """
Don't generate redundant step which is not available in the tasks. Below are some examples:

创建个文件问答系统: 1、上传文件并对文件内容进行问答。
Let’s think step by step.
1. Use 'FileRetrievalQA' to conduct question and answer on the upload file.

创建个知识库问答系统: 1、选择知识库并对知识库进行问答。
Let’s think step by step.
1. Use 'KnowledgeRetrievalQA' to conduct question and answer on the knowledge base.

创建个大模型对话系统: 1、跟大模型进行对话。
Let’s think step by step.
1. Use 'ConversationWithLLm' to chat or converse with large language model.

创建个数据库查询与分析系统：1、自然语言交互进行数据库查询与分析
Let’s think step by step.
1. Use 'SQLAnalysis' for database query and analysis using natural language.

创建个合同审核系统：1、上传合同pdf文件并对合同内容进行查询问答；2、当涉及到合同数值计算问题时，请调用计算器工具；3、当涉及到需要查外部信息时，请调用搜索引擎工具；
Let’s think step by step.
1. Use 'FileRetrievalQA' to conduct question and answer on the upload contract file.
2. Use 'Calculator' to compute numerical calculations related to the contract.
3. Use 'SerpAPI' to look up external information which is not included in the contract.

----------------------------
{instruction}
Let’s think step by step.

"""
