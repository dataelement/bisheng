from langchain_core.prompts.chat import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)


SEED_QUESTION_SYSTEM = SystemMessagePromptTemplate.from_template(
    """\
您的任务是遵循以下规则从给定的上下文中提出一个问题，规则如下：

    1. 即使在没有给定上下文的情况下，问题也应该对人类有意义。
    2. 应该可以从给定上下文中完全回答问题。
    3. 问题应该来自包含重要信息的上下文部分。它也可以来自表格、段落、或者代码等。
    4. 回答问题时不应包含任何链接。
    5. 问题的难度应该是中等的。
    6. 问题必须是合理的，并且必须能被人理解和回答。
    7. 不要在问题中使用“提供的上下文”等短语。
    8. 避免使用可以分解成多个问题的“和”字样来构建问题。
    9. 如果上下文是中文，那么问题也应该是中文的。

Examples:
context:武汉达梦数据库股份有限公司 招股说明书 （申报稿） 1-1-226 表中作出恰当列报。 2、研发费用 2021年度、 2020年度、 2019 年度，达梦数据 研发费用金额分别 为11,786.99 万元、 9,660.26 万元、 6,255.86万元， 各年度研发费用占营 业收入的比例分别为 15.86 % 、 21.46 %、20.74 %。 由于研发投入金额及其占当期 营业收入的比例是 达梦数据 的关键 指标之一，可能存在因为核算不准 确而导致的错报风险。因此， 中天 运会计师 将研发费用的归集和核算 确定为关键审计事项。 针对研发费用的真实性与准确性，会计师执行的 重要审计程序主要包括： （1）了解与研发费用相关的关键内部控制，评价 这些控制的设计，确定其是否得到执行，并对相关内 部控制的运行有效性进行测试； （2）获取研发项目立项、审批资料，抽查重要研 发项目的过程文档，判断研发项目的真实性； （3）获取研发费用按项目、性质分类明细表，分
question:达梦2021年的研发费用占营业收入的比例是多少？

context:武汉达梦数据库股份有限公司 招股说明书 （申报稿） 1-1-329 （2）存货周转率 公司与同行业可比公司存货周转率对比情况如下： 公司简称 2021年度 2020年度 2019年度 中望软件 6.93 5.62 10.66 星环科技 3.38 3.21 2.24 金山办公 212.60 175.46 162.91 平均值 74.30 61.43 58.60 本公司 1.13 0.57 0.87 数据来源：可比公司招股说明书、定期报告。 报告期各期， 公司存货周转率显著低于同行业可比公司存货周转率平均水平， 主要是因为公司将未验收的数据及行业解决方案项目所发生的累 计成本均作为 存货核算。报告期各期末，公司存在 “湖北省司法行政数据中心项目 ”、“政法云 大数据中心基础设施服务及大数据中心软件采购 项目”等金额较大且实施周期较 长的数据及行业解决方案项目，导致年末存货金额较大。
question:达梦2021年的存货周转率相较于前一年有何变化？
"""  # noqa: E501
)


SEED_QUESTION_HUMAN = HumanMessagePromptTemplate.from_template(
"""
context:{context}
question:
"""
)


SEED_QUESTION_CHAT_PROMPT = ChatPromptTemplate.from_messages(
    [
        SEED_QUESTION_SYSTEM,
        SEED_QUESTION_HUMAN
    ]
)


SCORE_CONTEXT_SYSTEM = SystemMessagePromptTemplate.from_template(
"""Evaluate the provided context and assign a numerical score between 0 and 10 based on the following criteria:
1. Award a high score to context that thoroughly delves into and explains concepts.
2. Assign a lower score to context that contains excessive references, acknowledgments, external links, personal information, or other non-essential elements.

And you should only output the score.

Examples:
Context:
01-2022.04.30 贷方发生额共 计 2535.43 万元，户名；X 贸易有限公司；\n③根据用款企业提供的增值税纳税申报表来看，2021 年度用款企业年累计开票额为\n7826.48 万元，年累计应纳税合计 95.32 万元，年累计已纳税额 86.23 万元；截止至 2022 年 3 月，用款企业累计开票额为 1986.54 万元，累计应纳税合计19.54 万元，累计已纳税额\n20.23 万元。\n根据核算用款企业的银行流水及企业会计记账系统，剔除借款人往来转账款，估算用款 企业年营业额约在 6000 万元左右(纳税申报营业额)，全部营业收入约 20000 万元左右，借 款人所在 X 贸易有限公司综合毛
利润率约为 35%，净利润约 20%左右。\n\n| 资产种类 | 坐落 | 产权人 | 建筑面积 | 现价值 | 贷款余额 | 资产净值 |\n| --- | --- | --- | --- | --- | --- | --- |\n| 房产 | HN 省 YY 市 PP 小区 5#2-101 | A | 240.20 | 365.23 万 | 165.
Score: 4

Context:
认缴出资额 200 万元 实缴出资额 200 万元 持股比例 20% |\n| 企业所属商圈 | 无 | 是否为已准入商圈 | 是□ 否 ☑ |\n(1) 企业经营历史及现状说明\nX 贸易有限公司 (下称“用款企业”) 注册成立于 2015 年 11 月，统一社会信用代码1234567890ACBDEFGH，法定代表人 A，公司注册地址位于 M 市 N 区 JF 路 20 号 NJ 大厦 18 楼1807 室，实际办公地址位于 M 市 N 区 K 广场 C 座 19 楼 1901、1906、1908、1910、1912、1914，办公面积为 880.51 ㎡，经营场所为用款企业租赁房产，租赁期限，现阶段年租金 73 万余元。\n用款企业是著名品牌“XYZ”的运营公司，是
以经营短袜、连裤袜、 内衣、家居服、配饰为主要品类的亲体织物公司，致力于为年轻消费群体提供“一站式”多品类亲体织物购物 体验。 作为织物文化的传播者和输出者，用款企业秉承一贯的高品质与原创精神，依托中国 研发团队，创领多项核心技术，不断建立并升级健康织物行业标准，目前拥有实用新型专利 6 项，发明专利 1 项，注册商标 30 余个，为品牌的商标保护构建了全面的商标防御体系。\n“XYZ”品牌创立于 2006 年，于 2009 年正式进入中国市场，在成立 10 年的时间里，在全国共有 400 余家店面，运营主要有以下三种模式：\n①直营模式：目前用款企业
管控的直营店有 100 家左右，其中在 M 地区共有 9 家直营店，分别为 Y1 店、Y2 店、Y3 店、Y4 店、Y5 店、Y6 店、Y7 店、Y8 店、Y9 店。经查看用款企业相关财务系统并截屏 ，用款企业 2021 年度 、2022 年 1-4 月直营店营业收入合计分别为7623.45 万元、1987.23 万元，M 地区 9 家直营店收入合计分别为 1238.67 万元、302.54 万元。根据数据测算直营部分毛利润率65%。
Score: 7
"""  # noqa: E501
)


SCORE_CONTEXT_HUMAN = HumanMessagePromptTemplate.from_template(
"""
Context:
{context}
Score:
"""  # noqa: E501
)


SCORE_CONTEXT_CHAT_PROMPT = ChatPromptTemplate.from_messages(
    [
        SCORE_CONTEXT_SYSTEM,
        SCORE_CONTEXT_HUMAN
    ]
)


FILTER_QUESTION_SYSTEM = SystemMessagePromptTemplate.from_template(
    """\
Determine if the given question can be clearly understood even when presented without any additional context. Specify reason and verdict is a valid json format.

Examples:
question: What is the discovery about space?
{{
    "reason":"The question is too vague and does not specify which discovery about space it is referring to."
    "verdit":"No"
}}

question: What caused the Great Depression?
{{
    "reason":"The question is specific and refers to a well-known historical economic event, making it clear and answerable.",
    "verdict":"Yes"
}}

question: What is the keyword that best describes the paper's focus in natural language understanding tasks?
{{
    "reason": "The question mentions a 'paper' in it without referring it's name which makes it unclear without it",
    "verdict": "No"
}}

question: Who wrote 'Romeo and Juliet'?
{{
    "reason": "The question is clear and refers to a specific work by name therefore it is clear",
    "verdict": "Yes"
}}

question: What did the study mention?
{{
    "reason": "The question is vague and does not specify which study it is referring to",
    "verdict": "No"
}}

question: What is the focus of the REPLUG paper?
{{
    "reason": "The question refers to a specific work by it's name hence can be understood", 
    "verdict": "Yes"
}}
"""  # noqa: E501
)


FILTER_QUESTION_HUMAN = HumanMessagePromptTemplate.from_template(
    """\
question:{question}
"""  # noqa: E501
)


FILTER_QUESTION_CHAT_PROMPT = ChatPromptTemplate.from_messages(
    [
        FILTER_QUESTION_SYSTEM,
        FILTER_QUESTION_HUMAN
    ]
)


ANSWER_FORMULATE = HumanMessagePromptTemplate.from_template(
    """\
Answer the question using the information from the given context. 

context:{context}

question:{question}
answer:
"""  # noqa: E501
)
