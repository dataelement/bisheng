PDF_IDX_PATH = "/home/public/FinGLM/C-data/C-list-pdf-name.txt"
# PDF_IDX_PATH = "/app/data/fin_glm/data/C-data/C-list-pdf-name.txt"
TXT_PATH = "/home/public/chatglm_llm_fintech_raw_dataset/alltxt"
import re
from pypinyin import lazy_pinyin


def all_variables(inputs: dict) -> dict:
    """
    db_schema.py
    """
    TABLE_NAME = "big"

    schema_meta = [
        "公司名称",
        "股票代码",
        "股票简称",
        "年份",
        "小数位数",  # 用来标记金融表是几位小数
    ]

    schema_base = [
        "外文名称",
        "法定代表人",
        "注册地址",
        "办公地址",
        "电子信箱",
        "网址",
    ]

    schema_emp = [
        '研发人员',
        '技术人员',
        "生产人员",
        "销售人员",
        "财务人员",
        "行政人员",
        '小学',
        '初中',
        '高中',
        '专科',
        '本科',
        '硕士',
        '博士',
        '中专',
        '职工总数',
    ]

    schema_edu = [
        '小学',
        '初中',
        '高中',
        '中专',
        '专科',
        '本科',
        '硕士',
        '博士',
    ]

    # 基础信息表
    base = [
        "股票简称",
        "证券简称",
        "股票代码",
        "证券代码",
        "公司名称",
        "企业名称",
        "公司简称",
        "企业简称",
        "外文名称",
        "外文简称",
        "法定代表人",
        "法人",
        "注册地址",
        "注册地址的邮政编码",
        "办公地址",
        "办公地址的邮政编码",
        "网址",
        "电子信箱",
        "传真",
        "联系地址",
    ]
    # 员工情况
    employee = [
        '技术人员',
        "生产人员",
        "销售人员",
        "财务人员",
        "行政人员",
        '小学',
        '初中',
        '高中',
        '专科',
        '本科',
        '硕士',
        '博士',
        '中专',
        '职工总数',
    ]

    # 合并资产负债表
    balance = [
        # '流动资产',
        '货币资金',
        '结算备付金',
        '拆出资金',
        '交易性金融资产',
        '衍生金融资产',
        '应收票据',
        '应收账款',
        '应收款项融资',
        '预付款项',
        '应收保费',
        '应收分保账款',
        '应收分保合同准备金',
        '其他应收款',
        '应收利息',
        '应收股利',
        '买入返售金融资产',
        '存货',
        '合同资产',
        '持有待售资产',
        '一年内到期的非流动资产',
        '其他流动资产',
        '流动资产合计',
        # '非流动资产',
        '发放贷款和垫款',
        '债权投资',
        '其他债权投资',
        '长期应收款',
        '长期股权投资',
        '其他权益工具投资',
        '其他非流动金融资产',
        '投资性房地产',
        '固定资产',
        '在建工程',
        '生产性生物资产',
        '油气资产',
        '使用权资产',
        '无形资产',
        '开发支出',
        '商誉',
        '长期待摊费用',
        '递延所得税资产',
        '其他非流动资产',
        '非流动资产合计',
        '资产总计',
        # '流动负债',
        '短期借款',
        '向中央银行借款',
        '拆入资金',
        '交易性金融负债',
        '衍生金融负债',
        '应付票据',
        '应付账款',
        '预收款项',
        '合同负债',
        '卖出回购金融资产款',
        '吸收存款及同业存放',
        '代理买卖证券款',
        '代理承销证券款',
        '应付职工薪酬',
        '应交税费',
        '其他应付款',
        '应付利息',
        '应付股利',
        '应付手续费及佣金',
        '应付分保账款',
        '持有待售负债',
        '一年内到期的非流动负债',
        '其他流动负债',
        '流动负债合计',
        # '非流动负债',
        '保险合同准备金',
        '长期借款',
        '应付债券',
        '租赁负债',
        '长期应付款',
        '长期应付职工薪酬',
        '预计负债',
        '递延收益',
        '递延所得税负债',
        '其他非流动负债',
        '非流动负债合计',
        '负债合计',
        # '所有者权益',
        '股本',
        '其他权益工具',
        '优先股',
        '永续债',
        '资本公积',
        '库存股',
        '其他综合收益',
        '专项储备',
        '盈余公积',
        '一般风险准备',
        '未分配利润',
        '归属于母公司所有者权益合计',
        '少数股东权益',
        '所有者权益合计',
        '负债和所有者权益总计',
    ]

    # 现金流量表
    cash = [
        # '经营活动产生的现金流量',
        '销售商品、提供劳务收到的现金',
        '客户存款和同业存放款项净增加额',
        '向中央银行借款净增加额',
        '向其他金融机构拆入资金净增加额',
        '收到原保险合同保费取得的现金',
        '收到再保业务现金净额',
        '保户储金及投资款净增加额',
        '收取利息、手续费及佣金的现金',
        '拆入资金净增加额',
        '回购业务资金净增加额',
        '代理买卖证券收到的现金净额',
        '收到的税费返还',
        '收到其他与经营活动有关的现金',
        '经营活动现金流入小计',
        '购买商品、接受劳务支付的现金',
        '客户贷款及垫款净增加额',
        '存放中央银行和同业款项净增加额',
        '支付原保险合同赔付款项的现金',
        '拆出资金净增加额',
        '支付利息、手续费及佣金的现金',
        '支付保单红利的现金',
        '支付给职工以及为职工支付的现金',
        '支付的各项税费',
        '支付其他与经营活动有关的现金',
        '经营活动现金流出小计',
        '经营活动产生的现金流量净额',
        # '投资活动产生的现金流量',
        '收回投资收到的现金',
        '取得投资收益收到的现金',
        '处置固定资产、无形资产和其他长期资产收回',
        '处置子公司及其他营业单位收到的现金净额',
        '收到其他与投资活动有关的现金',
        '投资活动现金流入小计',
        '购建固定资产、无形资产和其他长期资产支付',
        '投资支付的现金',
        '质押贷款净增加额',
        '取得子公司及其他营业单位支付的现金净额',
        '支付其他与投资活动有关的现金',
        '投资活动现金流出小计',
        '投资活动产生的现金流量净额',
        # '筹资活动产生的现金流量',
        '吸收投资收到的现金',
        '子公司吸收少数股东投资收到的现金',
        '取得借款收到的现金',
        '收到其他与筹资活动有关的现金',
        '筹资活动现金流入小计',
        '偿还债务支付的现金',
        '分配股利、利润或偿付利息支付的现金',
        '子公司支付给少数股东的股利、利润',
        '支付其他与筹资活动有关的现金',
        '筹资活动现金流出小计',
        '筹资活动产生的现金流量净额',
        '汇率变动对现金及现金等价物的影响',
        '现金及现金等价物净增加额',
        '期初现金及现金等价物余额',
        '期末现金及现金等价物余额',
    ]

    # 合并利润表
    income = [
        '营业总收入',
        '营业收入',
        '已赚保费',
        '手续费及佣金收入',
        '营业总成本',
        '营业成本',
        '利息支出',
        '手续费及佣金支出',
        '退保金',
        '赔付支出净额',
        '提取保险责任合同准备金净额',
        '保单红利支出',
        '分保费用',
        '税金及附加',
        '销售费用',
        '管理费用',
        '研发费用',
        '财务费用',
        '利息费用',
        '利息收入',
        '其他收益',
        '投资收益',
        '对联营企业和合营企业的投资收益',
        '以摊余成本计量的金融资产终止确认收益',
        '汇兑收益',
        '净敞口套期收益',
        '公允价值变动收益',
        '信用减值损失',
        '资产减值损失',
        '资产处置收益',
        '营业利润',
        '营业外收入',
        '营业外支出',
        '利润总额',
        '所得税费用',
        '净利润',
        '持续经营净利润',
        '终止经营净利润',
        '归属于母公司股东的净利润',
        '少数股东损益',
        '其他综合收益的税后净额',
        '归属母公司所有者的其他综合收益的税后净额',
        '不能重分类进损益的其他综合收益',
        '重新计量设定受益计划变动额',
        '权益法下不能转损益的其他综合收益',
        '其他权益工具投资公允价值变动',
        '企业自身信用风险公允价值变动',
        '将重分类进损益的其他综合收益',
        '权益法下可转损益的其他综合收益',
        '其他债权投资公允价值变动',
        '金融资产重分类计入其他综合收益的金额',
        '其他债权投资信用减值准备',
        '现金流量套期储备',
        '外币财务报表折算差额',
        '归属于少数股东的其他综合收益的税后净额',
        '综合收益总额',
        '归属于母公司所有者的综合收益总额',
        '归属于少数股东的综合收益总额',
        '基本每股收益',
        '稀释每股收益',
    ]

    schema_fin = balance + cash + income

    schema = schema_meta + schema_base + schema_fin + schema_emp

    schema_py2zh = {"_".join(lazy_pinyin(i)): i for i in schema}

    schema_zh2py = {v: k for k, v in schema_py2zh.items()}

    type_schema = [
        {"name": "meta", "type": "TEXT", "columns": schema_meta, "default_val": ""},
        {"name": "base", "type": "TEXT", "columns": schema_base, "default_val": ""},
        {"name": "fin", "type": "REAL", "columns": schema_fin, "default_val": 0.0},
        {"name": "emp", "type": "INTEGER", "columns": schema_emp, "default_val": 0},
    ]

    fillna_dict = {}
    for item in type_schema:
        cols = item["columns"]
        dval = item["default_val"]
        for col in cols:
            fillna_dict[col] = dval

    fillna_dict["小数位数"] = '2'

    db_schema_variables = {
        'table': TABLE_NAME,
        'schema': schema,
        'schema_py2zh': schema_py2zh,
        'schema_zh2py': schema_zh2py,
        'fillna_dict': fillna_dict,
        'type_schema': type_schema,
        'schema_fin': schema_fin,
        'schema_meta': schema_meta,
    }

    """
    keywords.py
    """
    titles = [i.strip() for i in open(PDF_IDX_PATH, encoding="utf-8").readlines() if i]
    comps = [i.split("_")[2] for i in titles]
    comps_code = [i.split("_")[4] for i in titles]
    comps_short = [i.split("_")[6] for i in titles]
    years = [i.split("_")[8] for i in titles]

    comp_title_dict = {}
    for i, comp in enumerate(comps):
        if comp not in comp_title_dict:
            comp_title_dict[comp] = []
        comp_title_dict[comp].append(titles[i])

    short_comp_dict = {}
    for name, short in zip(comps, comps_short):
        short_comp_dict[short] = name

    comp_short_dict = {}
    for name, short in zip(comps, comps_short):
        comp_short_dict[name] = short

    comps = set(comps)
    comps_code = set(comps_code)
    comps_short = set(comps_short)
    years = set(years)

    # 基础信息表
    base = [
        "股票简称",
        "证券简称",
        "股票代码",
        "证券代码",
        "公司名称",
        "企业名称",
        "公司简称",
        "企业简称",
        "外文名称",
        "外文简称",
        "法定代表人",
        "法人",
        "注册地址",
        "注册地址的邮政编码",
        "办公地址",
        "办公地址的邮政编码",
        "网址",
        "电子信箱",
        "传真",
        "联系地址",
    ]
    # 员工情况
    employee = [
        '技术人员',
        "生产人员",
        "销售人员",
        "财务人员",
        "行政人员",
        '小学',
        '初中',
        '高中',
        '专科',
        '本科',
        '硕士',
        '博士',
        '中专',
        '职工总数',
    ]

    # 主营业务分析
    business = [
        "研发投入",
        "研发人员",
    ]

    dep_map = {"公司简介": base, "合并资产负债表": balance, "合并现金流量表": cash, "合并利润表": income, "员工情况": employee, "主营业务分析": business}

    other_excel_words = [
        "研发人员",
        "股份总数",
    ]

    other_text_words = [
        "重大销售合同",
        "主要销售客户",
        "主要供应商",
        "审计意见",
        "社会责任",
        "核心竞争力",
        "现金流",
        "会计师事务",
        "董事长报告书",
        "员工情况",
        "研发投入",
        "主要会计数据",
        "控股股东",
        "资产及负债状况",
        "处罚及整改",
        "仲裁事项",
        "重大环保问题",
        "重大合同" "破产重整",
        "重大变化",
    ]

    other_cut_words = ["以上", "以下", "及以上", "及以下"]

    exact_search_words = cash + balance + income + other_excel_words
    corase_search_words = base + employee + other_text_words + business

    type1_keywords = base + cash + balance + income + employee + business + other_excel_words  # + other_text_words

    dep_inv_map = {}
    for k, v in dep_map.items():
        for i in v:
            if i in dep_inv_map:
                print(i)
            dep_inv_map[i] = k
    leng = sum([len(v) for v in dep_map.values()])
    inv_leng = len(dep_inv_map)
    assert leng == inv_leng, f"{leng} != {inv_leng}"
    schema_fin_filtered = [i for i in schema_fin if "、" not in i]
    schema_all = schema_base + schema_fin_filtered + schema_emp
    schema_set = set(schema_all)

    keywords_variables = {
        'comps': comps,
        'comps_code': comps_code,
        'comps_short': comps_short,
        'years': years,
        'comp_title_dict': comp_title_dict,
        'short_comp_dict': short_comp_dict,
        'comp_short_dict': comp_short_dict,
        'base': base,
        'employee': employee,
        'business': business,
        'dep_map': dep_map,
        'other_excel_words': other_excel_words,
        'other_text_words': other_text_words,
        'other_cut_words': other_cut_words,
        'exact_search_words': exact_search_words,
        'corase_search_words': corase_search_words,
        'type1_keywords': type1_keywords,
        'dep_inv_map': dep_inv_map,
        'schema_edu': schema_edu,
        'schema_fin_filtered': schema_fin_filtered,
        'schema_set': schema_set,
        'schema_emp': schema_emp,
        'schema_base': schema_base,
        'schema_edu': schema_edu,
    }

    """
    formulas.py
    """
    formulas = [
        {'target': '博士及以上的员工人数', 'sub': ['博士'], 'raw_formula': '博士', 'is_percent': False},
        {'target': '企业研发经费与利润比值', 'sub': ['研发费用', '净利润'], 'raw_formula': '研发费用/净利润', 'is_percent': False},
        {'target': '企业研发经费与营业收入比值', 'sub': ['研发费用', '营业收入'], 'raw_formula': '研发费用/营业收入', 'is_percent': False},
        {'target': '研发人员占职工人数比例', 'sub': ['研发人员', '职工总数'], 'raw_formula': '研发人员/职工总数', 'is_percent': False},
        {'target': '研发经费与利润比值', 'sub': ['研发费用', '净利润'], 'raw_formula': '研发费用/净利润', 'is_percent': False},
        {'target': '流动比率', 'sub': ['流动资产合计', '流动负债合计'], 'raw_formula': '流动资产合计/流动负债合计', 'is_percent': False},  # 变动
        {
            'target': '速动比率',
            'sub': ['流动资产合计', '流动负债合计', '存货'],
            'raw_formula': '(流动资产合计-存货)/流动负债合计',
            'is_percent': False,
        },  # 变动
        {'target': '企业硕士及以上人员占职工人数比例', 'sub': ['博士', '硕士', '职工总数'], 'raw_formula': '(硕士+博士)/职工总数', 'is_percent': False},
        {
            'target': '企业研发经费占费用比例',
            'sub': ['研发费用', '销售费用', '财务费用', '管理费用'],
            'raw_formula': '研发费用/(销售费用+财务费用+管理费用+研发费用)',
            'is_percent': False,
        },
        {
            'target': '企业研发经费占费用的比例',
            'sub': ['研发费用', '销售费用', '财务费用', '管理费用'],
            'raw_formula': '研发费用/(销售费用+财务费用+管理费用+研发费用)',
            'is_percent': False,
        },
        {'target': '营业利润率', 'sub': ['营业利润', '营业收入'], 'raw_formula': '营业利润/营业收入', 'is_percent': True},
        {'target': '资产负债比率', 'sub': ['负债合计', '资产总计'], 'raw_formula': '负债合计/资产总计', 'is_percent': True},  # 变动
        {'target': '现金比率', 'sub': ['流动负债合计', '货币资金'], 'raw_formula': '货币资金/流动负债合计', 'is_percent': True},  # 变动
        {'target': '非流动负债比率', 'sub': ['非流动负债合计', '负债合计'], 'raw_formula': '非流动负债合计/负债合计', 'is_percent': True},  # 变动
        {'target': '流动负债比率', 'sub': ['流动负债合计', '负债合计'], 'raw_formula': '流动负债合计/负债合计', 'is_percent': True},  # 变动
        {'target': '净资产收益率', 'sub': ['所有者权益合计', '净利润'], 'raw_formula': '净利润/所有者权益合计', 'is_percent': True},  # 变动
        {'target': '净利润率', 'sub': ['营业收入', '净利润'], 'raw_formula': '净利润/营业收入', 'is_percent': True},
        {'target': '营业成本率', 'sub': ['营业成本', '营业收入'], 'raw_formula': '营业成本/营业收入', 'is_percent': True},
        {'target': '管理费用率', 'sub': ['管理费用', '营业收入'], 'raw_formula': '管理费用/营业收入', 'is_percent': True},
        {'target': '财务费用率', 'sub': ['财务费用', '营业收入'], 'raw_formula': '财务费用/营业收入', 'is_percent': True},
        {'target': '毛利率', 'sub': ['营业收入', '营业成本'], 'raw_formula': '(营业收入-营业成本)/营业收入', 'is_percent': True},
        {
            'target': '三费比重',
            'sub': ['销售费用', '管理费用', '财务费用', '营业收入'],
            'raw_formula': '(销售费用+管理费用+财务费用)/营业收入',
            'is_percent': True,
        },
    ]

    formula_dict = {i["target"]: i for i in formulas}

    formulas_variables = {"formula_dict": formula_dict, "formulas": formulas}

    """
    alias.py
    """
    alias_dict = {
        '资产总计': ['资产总额', '资产合计'],
        "研发费用": ['研发经费'],
        "收回投资收到的现金": ["收回投资所收到的现金", "收回的投资收到的现金"],
        "期末现金及现金等价物余额": ["现金及现金等价物余额", "期末的现金及现金等价物余额", "现金及现金等价物"],
        "净利润": ["利润", "收益"],
        "职工总数": ["员工总数", "职工人数", "员工人数", "职工总人数"],
        "所有者权益合计": ["净资产"],
        "经营活动产生的现金流量净额": ["经营现金流量"],
        "电子信箱": ["电子邮箱地址", "电子邮箱"],
        "基本每股收益": ["每股收益"],
        "负债合计": ["总负债", "负债总计"],
        "归属于母公司股东的净利润": ["归属于母公司所有者的净利润"],
        "外文名称": ["英文名称"],
        "网址": ["互联网地址", "公司网址"],
        "本科": ["大学"],
        "专科": ["大专"],
        "公司名称": ["企业名称"],
        "股票简称": ["证券简称"],
        "股票代码": ["证券代码"],
        "股份总数": ["总股本"],
        "无形资产": ["无形资产总额"],
        "货币资金": ["货币总额"],
        "资产总计": ["总资产", "资产总额", "资产合计"],
        "流动负债合计": ["流动负债"],
        "非流动负债合计": ["非流动负债"],
        "股本": ["实收资本"],
        "流动资产合计": ["流动资产"],
        "非流动资产合计": ["非流动资产"],
    }

    alias_inv_dict = {}
    for k, v in alias_dict.items():
        for u in v:
            alias_inv_dict[u] = k

    alias_variables = {"alias_dict": alias_dict, "alias_inv_dict": alias_inv_dict}

    """
    others
    """
    import jieba

    jieba.del_word("以上学历")
    for word in type1_keywords + other_text_words + other_cut_words + list(formula_dict.keys()):
        jieba.add_word(word)

    for comp in comps | comps_short:
        jieba.add_word(comp)

    for k, v in alias_inv_dict.items():
        jieba.add_word(k)
        jieba.add_word(v)

    DB_PATH = '/home/youjiachen/workspace/FinGLM/code/finglm5/serving/db/online.db'
    others = {
        "_jieba": jieba,
        "DB_PATH": DB_PATH,
        'stopwords_path': '/home/public/FinGLM/stopwords.txt',
        # 'stopwords_path': '/opt/server/bisheng-test/bisheng/data/fin_glm/resources/stopwords.txt',
        'stopwordsv2_path': '/home/public/FinGLM/stopwords_v2.txt',
        # 'stopwordsv2_path': '/opt/server/bisheng-test/bisheng/data/fin_glm/resources/stopwords_v2.txt',
        'VECTOR_SEARCH_THRESHOLD_2': -100,
        'ENCODER_NORMALIZE_EMBEDDINGS': True,
        'ENCODER_MODEL_PATH': '/home/public/llm/text2vec-large-chinese',
        # 'ENCODER_MODEL_PATH': '/opt/server/bisheng-test/bisheng/data/fin_glm/text2vec-large-chinese',
        "MAX_KLG_LENGTH": 1600,
        'VECTOR_CACHE_PATH': '/home/public/FinGLM/vector_cache',
    }
    
    fin_set = set(schema_fin)
    base_set = set(schema_base)
    emp_set = set(schema_emp)

    base_map = {
        "英文名称": "外文名称",
        "电子邮箱": "电子信箱",
        "互联网地址": "网址"
    }
    emp_map = {
        "研发人员数量": "研发人员",
        "研究生": "硕士",
        "大学": "本科",
        "大专": "专科",
        "合计": "职工总数"
    }
    export_fin_table_names = ["合并利润表", "合并资产负债表", "合并现金流量表"]
    tables_pattern = re.compile("合并利润表|合并资产负债表|母公司资产负债表|母公司利润表|合并现金流量表|母公司现金流量表|所有者权益变动表")

    patterns = [
        re.compile("目录"),
        re.compile("第[一二三四五六七八九十]+[章节]"),
        re.compile("[一二三四五六七八九十]+[、. ]"),
        re.compile("[（(][一二三四五六七八九十]+[)）][、. ]*"),
        re.compile("[1234567890]+[、. ]"),
        re.compile("[(（][1234567890]+[)）][、. ]*")
    ]

    dirty_patterns = [
        re.compile("\d+/\d+"),
        re.compile("年度报告")
    ]

    cell_dirty_patterns = [
        re.compile("[一二三四五六七八九十][、. -][\(（]*[一二三四五六七八九十\d]+[\)）]*"),
        re.compile("注释[:：、 一二三四五六七八九十\d]+")
    ]
    
    doc_tree_variables = {
        "fin_set": fin_set,
        "base_set": base_set,
        "emp_set": emp_set,
        "base_map": base_map,
        "emp_map": emp_map,
        "export_fin_table_names": export_fin_table_names,
        "tables_pattern": tables_pattern,
        "patterns": patterns,
        "dirty_patterns": dirty_patterns,
        "cell_dirty_patterns": cell_dirty_patterns,
        "TXT_PATH": TXT_PATH,
    }

    return dict(**keywords_variables, **formulas_variables, **db_schema_variables, **alias_variables, **doc_tree_variables, **others)


all_glob_variables = list(all_variables([]).keys())