import re
import sqlite3
def trans_solve_type2(inputs: dict) -> dict:
    " 关键词为计算题所需词"
    def year_add(year, delta): return str(int(year[:-1]) + delta) + "年"
    
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
    
    keyword = inputs["keyword"]
    comp_name = inputs["comp_name"]
    year = inputs["year"]
    query = inputs["query"]
    comp_short_dict = inputs["comp_short_dict"]
    schema = inputs['schema']
    schema_fin = inputs['schema_fin']
    schema_emp = inputs['schema_emp']
    DB_PATH = inputs['DB_PATH']
    db = sqlite3.connect(DB_PATH)
    cursor = db.cursor()
    
    res = []
    extra_output = ""
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
        # TODO: TYPE1
        # else:
        #     type1_res = solve_type1(comp_name, sub_year, sub_word, **kwargs)
        #     res_v = find_res_value(type1_res, sub_word)

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

def transform_extra_outputs2text(inputs: dict) -> dict:
    answer = inputs['extra_outputs']
    return {'answer': answer}