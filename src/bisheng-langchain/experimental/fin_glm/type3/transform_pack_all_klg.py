from loguru import logger
def transform_pack_all_klg_v2(inputs: dict) -> dict:
    def get_desc_klg(pdf):
        if pdf == "":
            return ""
        try:
            _, _, comp_name, _, comp_code, _, comp_short, _, report_year, _, _ = pdf.split("_")
            return f"企业名称为{comp_name}（简称{comp_short}, 股票/证券代码{comp_code}）的年报"
        except:
            return ""
    def get_year_doc(comp_name, year):
        comp_title_dict = inputs["comp_title_dict"]
        
        def year_add(year, delta): return str(int(year[:-1]) + delta) + "年"
        
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
    
    logger.info("打包相关文本V2 transform_pack_all_klgV2")
    klg = ""
    desc_klg = ""
    MAX_KLG_LENGTH = inputs["MAX_KLG_LENGTH"]
    try:
        result = inputs["query_analyze_result"]
        comp_name = result["comps"][0]
        year = result['years'][0]
        keywords = result["keywords"]
        query = inputs["query"]
        dt = inputs["doc_tree"]
        comp_short_dict = inputs["comp_short_dict"]
        years = inputs["years"]
        pdf = get_year_doc(comp_name, year)
        hop = 0
        k = 20
        if keywords:
            nodes = dt.search_node(keywords[0].word)
            all_children = []
            for node in nodes:
                all_children += [i.get_dep_str(hop=hop) for i in node.get_all_leaves("", only_excel_node=False) if i not in all_children]
            klg = "\n".join([str(i) for i in all_children[:k]])

                
        if not klg:
            if comp_name not in query:
                comp_name = comp_short_dict[comp_name]

            dt_query = query.replace(comp_name, "公司")
            for year in years:
                dt_query = dt_query.replace(year, "")
            
            node = dt.vector_search_node(dt_query)[0][0]
            klg = "\n".join([i.get_dep_str(hop=hop) for i in node.get_all_leaves("", only_excel_node=False)][:k])
        desc_klg = get_desc_klg(pdf)
    except Exception as e:
            logger.info("没有Doctree")
            pass
    logger.info(f"klg: {klg}, desc_klg: {desc_klg}")
    return {"klg": klg[:MAX_KLG_LENGTH], "desc_klg": desc_klg}