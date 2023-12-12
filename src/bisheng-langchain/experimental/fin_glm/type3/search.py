import os
import sys
import pdb
sys.path.append(os.path.dirname(os.getcwd()))
sys.path.append(os.getcwd())
import openai
from langchain.chains import LLMChain, TransformChain, SequentialChain
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate
from fin_qa.build_prompt import query_prompt_template
from rule_router import RuleBasedRouter
from multi_router import MultiRuleChain
# from predict_v1 import solve_type1
from loguru import logger
from doc_treev1 import transform2dt
from llmchain.ori_llm import klg_llm_chain
from type3.transform_pack_all_klg import transform_pack_all_klg_v2
from type3.trans_solve_type2 import transform_extra_outputs2text
import re
import sqlite3

openai.api_key = os.getenv("OPENAI_API_KEY")
openai.proxy = {"http": 'http://118.195.232.223:39995', "https": 'http://118.195.232.223:39995'}

llm = OpenAI(model_name='gpt-3.5-turbo-16k-0613', temperature=0.5)
llm_chain = LLMChain(llm=llm,
                     prompt=PromptTemplate.from_template(query_prompt_template),
                     output_key='answer',
                     )

transform_analyze2dt_chain = TransformChain(
    input_variables=["query_analyze_result"], output_variables=["doc_tree"], transform=transform2dt
)

transform_pack_all_klg_chain  = TransformChain(
    input_variables=["query_analyze_result", "query", "doc_tree"], output_variables=["klg", "desc_klg"], transform=transform_pack_all_klg_v2
)

solve_type2_chain = TransformChain(
    input_variables=["extra_outputs"], output_variables=["answer"], transform=transform_extra_outputs2text
)

solve_type31_llm_chain = SequentialChain(
    chains=[transform_analyze2dt_chain, transform_pack_all_klg_chain, klg_llm_chain],
    input_variables=["query", "query_analyze_result"],
    output_variables=["answer"],
    # verbose=True, 
)

def get_rule_based_search_chain():
    """
    router: 走type3根据问题分析结果兜底
    """
    def router(inputs) -> dict:
        comp_short_dict = inputs["comp_short_dict"]
        schema = inputs['schema']
        schema_fin = inputs['schema_fin']
        schema_emp = inputs['schema_emp']
        DB_PATH = inputs['DB_PATH']
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        
        def year_add(year, delta): return str(int(year[:-1]) + delta) + "年"
        def get_year_doc(comp_name, year):
            comp_title_dict = inputs["comp_title_dict"]
            
            docs = comp_title_dict[comp_name]
            for doc in docs:
                if year in doc:
                    return doc
            
            for doc in docs:
                if year_add(year, 1) in doc:
                    return doc
                
            for doc in docs:
                if year_add(year, -1) in doc:
                    return doc
            return docs[0] if docs else None
        def find_res_value(raw_res, keyword):
            def strip_comma(string): return string.replace(",", "")
            if raw_res == '':
                return ''
            res = raw_res
            raw_keyword = keyword
            keyword = str(keyword)
            res = re.sub("\d{4}年", "", res)
            res = re.sub("股票/证券代码\d+", "", res)
            res = re.sub('".+"', "", res)
            start = res.find(keyword) + len(keyword)
            values = re.findall("[-\d,.]+", res[start:])
            values = [i for i in values if i not in "-,."]
            res_v = None
            try:
                if len(values) > 0:
                    res_v = strip_comma(values[0])

                if res_v != None:
                    return res_v
            except Exception as e:
                print(e)
                return ''
            return ''
        def my_float(string):
            if not string: return 0.
            try:
                return float(string)
            except Exception as e:
                print(e)
                return 0.
            return 0.        
        """utils"""
        
        def query_single_klg(cursor, table_name, comp, year, keyword):
            "rule2sql"
            short_comp_dict = inputs["short_comp_dict"]
            schema_zh2py = inputs["schema_zh2py"]
            schema_fin = inputs["schema_fin"]
            schema_emp = inputs["schema_emp"]
            
            def algin_float_string(v, dot_bits):
                format_v_string = "{:." + dot_bits + "f}"
                v = format_v_string.format(v)
                return v
            
            if comp in short_comp_dict:
                comp = short_comp_dict[comp]
            sql = f"""
            SELECT xiao_shu_wei_shu, gu_piao_jian_cheng, {schema_zh2py[keyword.word]}
            FROM {table_name}
            WHERE
                gong_si_ming_cheng = "{comp}"
                AND nian_fen = "{year}"
            """
            unit = "元" if keyword.word in schema_fin else ""
            unit = "人" if keyword.word in schema_emp else unit
            try:
                ret = cursor.execute(sql).fetchone()
                if not ret:
                    return ""
                dot_bits = ret[0]
                abb = ret[1]
                val = ret[2]
        
                if val == "" or (val == 0 and unit != "人"):
                    return ""

                if isinstance(val, float):
                    val = algin_float_string(val, dot_bits)

                return f"{comp}(简称{abb})在{year}的{str(keyword)}是{val}{unit}。"
            except Exception as e:
                print("qeury_single_klg_err", e)
            
            return ""
        """du_utils"""
        class Keyword:
            def __init__(self, word, type, formula="", is_percent=False, raw_word=""):
                dep_inv_map = inputs['dep_inv_map']
                self.word = word
                self.type = type
                # self.aliases = set()
                self.raw_word = raw_word if raw_word else word
                # print("#", raw_word, self.raw_word)
                self.is_percent = is_percent
                self.key_title = dep_inv_map.get(word, word)
                self.formula = formula
                self.sub = self.parse_formula(formula)

            def __str__(self):
                return self.raw_word

            def parse_formula(self, formula):
                sub = list(set([i for i in re.split("[=/()+-]", formula) if i != ""]))
                return [Keyword(i, type=1) for i in sorted(sub, key=len, reverse=True)]

            def get_sub_word_by_name(self, name):
                for word in self.sub:
                    if word.word == name:
                        return word
                return None    
        def solve_type1(comp_name, year, keyword, query="", **kwargs):
            "单次完成的客观基础查询"
            if query == "":
                query = f"{comp_name}在{year}的{keyword}是？"
            klg = ""
            if keyword.word in schema:
                klg = query_single_klg(cursor, "big", comp_name, year, keyword)
                if klg == "":
                    return "抱歉，我没有找到您需要的数据，对于您问题的答案是不知道。"
            return klg
        
        def solve_type2(comp_name, year, keyword, query, **kwargs):
            " 关键词为计算题所需词"
            values = []
            formula = keyword.formula
            format_output = ""

            # 使得公司名称和query中的保持严格一致
            if comp_name not in query:
                comp_name = comp_short_dict[comp_name]
            
            export_dict = {}
            for word in keyword.sub:
                if word.word.startswith("上年"):
                    sub_year = year_add(year, -1)            
                    sub_word = Keyword(word.word[2:], type=1, raw_word=word.raw_word[2:])
                else:
                    sub_year = year
                    sub_word = Keyword(word.word, type=1, raw_word=word.raw_word)

                # print("DEBUG", sub_year, sub_word.word, sub_word.raw_word)
                # 尝试通过数据库先找，数据库找不到再递归调用。
                res_v = ""
                if sub_word.word in schema:
                    res_v = find_res_value(query_single_klg(cursor, "big", comp_name, sub_year, sub_word), sub_word)
                else:
                    type1_res = solve_type1(comp_name, sub_year, sub_word, **kwargs)
                    res_v = find_res_value(type1_res, sub_word)

                if res_v == "":
                    format_output += f"抱歉，没有找到{comp_name}在{sub_year}的{sub_word}。"
                    continue
                
                unit = ""
                if "每股" in sub_word.word:
                    unit = "元/股"
                elif sub_word.word in schema_fin:
                    unit = "元"
                elif sub_word.word in schema_emp:
                    unit = "人"

                if format_output:
                    if sub_year in format_output:
                        format_output += f"{sub_word}为{res_v}{unit}，"
                    else:
                        format_output += f"{sub_year}{sub_word}为{res_v}{unit}，"
                else:
                    format_output += f"{comp_name}{sub_year}{sub_word}为{res_v}{unit}，"
                values.append(my_float(res_v))

                if "增长率" in keyword.word:
                    export_dict[sub_year + sub_word.word] = res_v
                else:
                    export_dict[word.word] = res_v

            if len(values) != len(keyword.sub):
                format_output += f"无法为您计算{year}{comp_name}的{keyword}。"
                return [], format_output

            for i, k in enumerate(keyword.sub):
                formula = formula.replace(k.word, f"{values[i]}")
            try:
                ans = eval(formula)
            except Exception as e:
                print(formula)
                ans = 1

            if ("以上" in keyword.word or "以下" in keyword.word) and "/" not in keyword.formula:
                ans = int(ans)
                export_dict[keyword.word] = ans
                format_output += f"根据公式，{keyword}={keyword.formula}，得出结果{comp_name}{year}{keyword}为{ans}人。"
                # format_output += f"计算得出{comp_name}{year}{keyword}为{ans}人。"
            else:
                ans_1 = f"{ans:.2%}"
                ans_2 = f"{ans:.2f}"

                format_output += f"根据公式，{keyword}={keyword.formula}，得出结果{comp_name}{year}{keyword}为{ans_1}或{ans_2}。"
                # format_output += f"计算得出{comp_name}{year}{keyword}为{ans_1}或{ans_2}。"
                export_dict[keyword.word] = f"{ans_1}或{ans_2}"
            # print({"sql_res": export_dict, "query": query, "answer": format_output})

            return [], format_output            
        
        query = inputs.get('query')
        result = inputs.get("query_analyze_result")
        comp_names = []
        years = []
        if result != None:
            comp_names = result["comps"]
            years = result['years']
            keywords = result["keywords"]
            
        # type3-2 
        if (not comp_names) or (not years):
            return {'destination': 'type32', 'next_inputs': inputs}
        # 一个查询文档一个直接查询的关键词，打包一次
        if len(comp_names) == 1 and len(years) == 1 and len(keywords) == 1 and keywords[0].type == 1:
            pdf = get_year_doc(comp_names[0], years[0])
            inputs.update({"pdf": pdf})
            if pdf == None:
                return {'destination': 'type32', 'next_inputs': inputs}
            return  {'destination': 'type31', 'next_inputs': inputs}
        # 多个查询文档or多个关键词，打包多次
        res_prompts = []
        extra_outputs = []
        for comp_name in comp_names:
            for year in years:
                #  keywords 为空, 3-1向量召回
                if not keywords:
                    return  {'destination': 'type31', 'next_inputs': inputs}

                for keyword in keywords:
                    if keyword.type == 1:
                        logger.info("search: type 1")
                        res_prompts.append(solve_type1(comp_name, year, keyword))
                    elif keyword.type == 2:
                        logger.info("search: type 2")
                        res, extra = solve_type2(comp_name, year, keyword, query)
                        res_prompts += res
                        extra_outputs.append(extra)
                    elif keyword.type == 3:
                        return  {'destination': 'type31', 'next_inputs': inputs}
        # type2 计算题走rule
        if extra_outputs:
            inputs.update({'extra_outputs': "".join(res_prompts) + "".join(extra_outputs)})
            return {'destination': 'type2', 'next_inputs': inputs}
        if res_prompts:
            return  {'destination': 'type31', 'next_inputs': inputs}
        
    def routerv1(inputs) -> dict:
        "bisheng 上的简化版本router"
        # logger.add('/app/data/fin_glm/type3.log')
        logger.info("search: routerv1")
        # logger.add('/app/data/fin_glm/type3.log')
        logger.info("search: routerv1")
        comp_title_dict = inputs["comp_title_dict"]
        def year_add(year, delta): return str(int(year[:-1]) + delta) + "年"
        def get_year_doc(comp_name, year):
            
            docs = comp_title_dict[comp_name]
            for doc in docs:
                if year in doc:
                    return doc
            
            for doc in docs:
                if year_add(year, 1) in doc:
                    return doc
                
            for doc in docs:
                if year_add(year, -1) in doc:
                    return doc
            return docs[0] if docs else None
        
        result = inputs["query_analyze_result"]
        comp_names = []
        years = []
        if result != None:
            comp_names = result["comps"]
            years = result['years']
            keywords = result["keywords"]
        # type3-2 
        if (not comp_names) or (not years):
            return {'destination': None, 'next_inputs': inputs}
        # 一个查询文档一个直接查询的关键词，打包一次
        if len(comp_names) == 1 and len(years) == 1 and len(keywords) == 1 and keywords[0].type == 1:
            pdf = get_year_doc(comp_names[0], years[0])   
            if pdf == None:
                return {'destination': None, 'next_inputs': inputs}
        logger.info("search: type31")
        return {'destination': 'type31', 'next_inputs': inputs}
    
    rule_router = RuleBasedRouter(rule_function=router, input_variables=['query', 'query_type', "query_analyze_result"])

    chain_infos = [
        {'name': 'type2', 'chain': solve_type2_chain},
        {'name': 'type31', 'chain': solve_type31_llm_chain},
        {'name': 'type32', 'chain': llm_chain},
    ]

    destination_chains = {}
    for chain_info in chain_infos:
        destination_chains[chain_info['name']] = chain_info['chain']

    chain = MultiRuleChain(
        router_chain=rule_router,
        destination_chains=destination_chains,
        default_chain=llm_chain,
        # verbose=True,
        output_variables=['answer']
    )
    return chain

solve_type3_chain = get_rule_based_search_chain()