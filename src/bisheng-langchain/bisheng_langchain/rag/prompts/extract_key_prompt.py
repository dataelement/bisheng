from langchain.prompts.prompt import PromptTemplate


EXTRACT_KEY_PROMPT = PromptTemplate(
    input_variables=['question'],
    template="""分析给定Question，提取Question中包含的KeyWords，输出列表形式

Examples:
Question: 达梦公司在过去三年中的流动比率如下：2021年：3.74倍；2020年：2.82倍；2019年：2.05倍。
KeyWords: ['过去三年', '流动比率', '2021', '3.74', '2020', '2.82', '2019', '2.05']

----------------
Question: {question}
KeyWords: """,
)

# EXTRACT_KEY_PROMPT = PromptTemplate(
#     input_variables=['question'],
#     template="""分析给定Question，提取Question中包含的KeyWords，输出列表形式

# Examples:
# Question: 能否根据2020年金宇生物技术股份有限公司的年报，给我简要介绍一下报告期内公司的社会责任工作情况？
# KeyWords: ['报告期', '社会责任', '工作情况']

# Question: 请根据江化微2019年的年报，简要介绍报告期内公司主要销售客户的客户集中度情况，并结合同行业情况进行分析。
# KeyWords: ['报告期', '主要', '销售客户', '客户集中度', '同行业', '分析']

# Question: 请问，在苏州迈为科技股份有限公司2019年的年报中，现金流的情况是否发生了重大变化？若发生，导致重大变化的原因是什么？
# KeyWords: ['现金流', '重大变化', '原因']

# ----------------
# Question: {question}
# KeyWords: """,
# )