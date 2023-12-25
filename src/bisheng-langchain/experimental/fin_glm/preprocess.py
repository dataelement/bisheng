
def query_analyze(inputs: dict) -> dict:
    import re
    jieba = inputs['_jieba']
    query = inputs['query']
    comps = inputs['comps']
    comps_short = inputs['comps_short']
    short_comp_dict = inputs['short_comp_dict']

    query = re.sub("[(（）)]", "", query)
    query = query.replace("每股的", "每股")
    query_words = jieba.lcut(query)

    def exact_search_query(query, query_words):
        comp_names = []
        comp_short_names = []
        years = re.findall("\d{4}年", query)

        qwords = jieba.cut(query)
        for qword in qwords:
            if qword in comps:
                comp_names.append(qword)
            elif qword in comps_short:
                comp_short_names.append(qword)

        return comp_names, comp_short_names, years

    def extract_comps_and_years(query, query_words):
        # 先进行精准召回
        comp_names, comp_short_names, years = exact_search_query(query, query_words)
        # 公司名
        for short in comp_short_names:
            comp_name = short_comp_dict[short]
            if comp_name not in comp_names:
                comp_names.append(comp_name)

        return comp_names, years

    comp_names, years = extract_comps_and_years(query, query_words)
    return {"comps_and_years": {"years": years, "comps": comp_names}}


import re
from copy import deepcopy

import jieba


def trans_extract_keywords(inputs: dict) -> dict:
    alias_inv_dict = inputs['alias_inv_dict']
    schema = inputs['schema']
    schema_edu = inputs['schema_edu']
    formula_dict = inputs['formula_dict']
    dep_inv_map = inputs['dep_inv_map']
    other_text_words = inputs['other_text_words']
    comps_and_years = inputs['comps_and_years']
    jieba = inputs['_jieba']

    query = inputs['query']
    query_words = jieba.lcut(query)

    class Keyword:
        def __init__(self, word, type, formula="", is_percent=False, raw_word=""):
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

    def extract_keywords(query, query_words):
        def last_year_keyword(keyword):
            new_keyword = deepcopy(keyword)
            new_keyword.word = "上年" + new_keyword.word
            new_keyword.raw_word = "上年" + new_keyword.raw_word
            for i in range(len(new_keyword.sub)):
                word = new_keyword.sub[i]
                new_keyword.formula = new_keyword.formula.replace(word.word, "上年" + word.word)
                new_keyword.sub[i] = "上年" + word.word
            return new_keyword

        keywords = []
        # print(query_words)
        for raw_word in query_words:
            word = raw_word
            # print(word, raw_word)
            if word in alias_inv_dict:
                word = alias_inv_dict[word]
            # print(word, raw_word)
            # type2
            if word in formula_dict:
                detail = formula_dict[word]
                new_keyword = Keyword(
                    word, type=2, formula=detail["raw_formula"], is_percent=detail["is_percent"], raw_word=raw_word
                )
                keywords.append(new_keyword)
            # type1
            elif word in schema:
                keywords.append(Keyword(word, type=1, formula=word, raw_word=raw_word))
            # 较为泛型的 type2
            elif word in ('及以上', '及以下', '以上', '以下') and keywords[-1].word in schema_edu:
                if len(keywords) >= 1:
                    edu_idx = schema_edu.index(keywords[-1].word)
                    all_edus = []
                    if "以上" in word:
                        all_edus += schema_edu[edu_idx + 1 :]
                    elif "以下" in word:
                        all_edus += schema_edu[:edu_idx]
                    if "及" in word:
                        all_edus.append(keywords[-1].word)
                    all_edus.sort(key=lambda x: schema_edu.index(x))
                    all_edus_str = "+".join(all_edus)
                    new_keyword = Keyword(
                        f"{keywords[-1].word}{word}",
                        type=2,
                        formula=f"{all_edus_str}",
                        raw_word=f"{keywords[-1].raw_word}{word}",
                    )
                    keywords = keywords[:-1] + [new_keyword]
            elif word in ('比率', '比例', '比值', '比'):
                if len(keywords) >= 2:
                    s = query.index(keywords[-2].raw_word)
                    e = query.index(raw_word) + len(raw_word)
                    new_keyword = Keyword(
                        f"{keywords[-2].word}和{keywords[-1].word}的比",
                        type=2,
                        formula=f"({keywords[-2].formula})/({keywords[-1].formula})",
                        raw_word=query[s:e],
                        is_percent=False,
                    )
                    last_2_keyword = new_keyword.get_sub_word_by_name(keywords[-2].word)
                    if last_2_keyword != None:
                        last_2_keyword.raw_word = keywords[-2].raw_word
                    last_1_keyword = new_keyword.get_sub_word_by_name(keywords[-1].word)
                    if last_1_keyword != None:
                        last_1_keyword.raw_word = keywords[-1].raw_word
                    keywords = keywords[:-2] + [new_keyword]
            elif word in ('增长率'):
                if len(keywords) >= 1:
                    s = query.index(keywords[-1].raw_word)
                    e = query.index(raw_word) + len(raw_word)
                    last_keyword = last_year_keyword(keywords[-1])
                    new_keyword = Keyword(
                        f"{keywords[-1].word}增长率",
                        type=2,
                        formula=f"({keywords[-1].formula}-{last_keyword.formula})/{last_keyword.formula}",
                        raw_word=query[s:e],
                        is_percent=True,
                    )

                    last_2_keyword = new_keyword.get_sub_word_by_name(last_keyword.word)
                    if last_2_keyword != None:
                        last_2_keyword.raw_word = last_keyword.raw_word
                    last_1_keyword = new_keyword.get_sub_word_by_name(keywords[-1].word)
                    if last_1_keyword != None:
                        last_1_keyword.raw_word = keywords[-1].raw_word
                    keywords = keywords[:-1] + [new_keyword]
            elif word in other_text_words:
                keywords.append(Keyword(word, type=3))

        return keywords

    keywords = extract_keywords(query, query_words)
    query_analyze_result = {"keywords": keywords}
    for key in comps_and_years:
        query_analyze_result[key] = comps_and_years[key]

    return {"query_analyze_result": query_analyze_result}

'''

Chain

'''
from all_variables import all_glob_variables, all_variables
from langchain.chains import SequentialChain, TransformChain
from preprocess import query_analyze, trans_extract_keywords

preprocess_tsfm_chain_0 = TransformChain(
    input_variables=["query"],
    output_variables=all_glob_variables,
    transform=all_variables,
)
preprocess_tsfm_chain_1 = TransformChain(
    input_variables=["query"],
    output_variables=["comps_and_years"],
    transform=query_analyze,
)
preprocess_tsfm_chain_2 = TransformChain(
    input_variables=["query"],
    output_variables=["query_analyze_result"],
    transform=trans_extract_keywords,
)

